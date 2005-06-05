from unittest import TestCase, makeSuite
from pkg_resources import *
import pkg_resources, sys
from sets import ImmutableSet

class Metadata:
    """Mock object to return metadata as if from an on-disk distribution"""

    def __init__(self,*pairs):
        self.metadata = dict(pairs)

    def has_metadata(self,name):
        return name in self.metadata

    def get_metadata(self,name):
        return self.metadata[name]

    def get_metadata_lines(self,name):
        return yield_lines(self.get_metadata(name))


class DistroTests(TestCase):

    def testCollection(self):
        # empty path should produce no distributions
        ad = AvailableDistributions([], python=None)
        self.assertEqual(list(ad), [])
        self.assertEqual(len(ad),0)
        self.assertEqual(ad.get('FooPkg'),None)
        self.failIf('FooPkg' in ad)
        ad.add(Distribution.from_filename("FooPkg-1.3_1.egg"))
        ad.add(Distribution.from_filename("FooPkg-1.4-py2.4-win32.egg"))
        ad.add(Distribution.from_filename("FooPkg-1.2-py2.4.egg"))

        # Name is in there now
        self.failUnless('FooPkg' in ad)

        # But only 1 package
        self.assertEqual(list(ad), ['foopkg'])
        self.assertEqual(len(ad),1)

        # Distributions sort by version
        self.assertEqual(
            [dist.version for dist in ad['FooPkg']], ['1.4','1.3-1','1.2']
        )
        # Removing a distribution leaves sequence alone
        ad.remove(ad['FooPkg'][1])
        self.assertEqual(
            [dist.version for dist in ad.get('FooPkg')], ['1.4','1.2']
        )
        # And inserting adds them in order
        ad.add(Distribution.from_filename("FooPkg-1.9.egg"))
        self.assertEqual(
            [dist.version for dist in ad['FooPkg']], ['1.9','1.4','1.2']
        )

        path = []
        req, = parse_requirements("FooPkg>=1.3")

        # Nominal case: no distros on path, should yield all applicable
        self.assertEqual(ad.best_match(req,path).version, '1.9')

        # If a matching distro is already installed, should return only that
        path.append("FooPkg-1.4-py2.4-win32.egg")
        self.assertEqual(ad.best_match(req,path).version, '1.4')

        # If the first matching distro is unsuitable, it's a version conflict
        path.insert(0,"FooPkg-1.2-py2.4.egg")
        self.assertRaises(VersionConflict, ad.best_match, req, path)

        # If more than one match on the path, the first one takes precedence
        path.insert(0,"FooPkg-1.4-py2.4-win32.egg")
        self.assertEqual(ad.best_match(req,path).version, '1.4')

    def checkFooPkg(self,d):
        self.assertEqual(d.name, "FooPkg")
        self.assertEqual(d.key, "foopkg")
        self.assertEqual(d.version, "1.3-1")
        self.assertEqual(d.py_version, "2.4")
        self.assertEqual(d.platform, "win32")
        self.assertEqual(d.parsed_version, parse_version("1.3-1"))

    def testDistroBasics(self):
        d = Distribution(
            "/some/path",
            name="FooPkg",version="1.3-1",py_version="2.4",platform="win32"
        )
        self.checkFooPkg(d)
        self.failUnless(d.installed_on(["/some/path"]))
        self.failIf(d.installed_on([]))

        d = Distribution("/some/path")
        self.assertEqual(d.py_version, sys.version[:3])
        self.assertEqual(d.platform, None)

    def testDistroParse(self):
        d = Distribution.from_filename("FooPkg-1.3_1-py2.4-win32.egg")
        self.checkFooPkg(d)

    def testDistroMetadata(self):
        d = Distribution(
            "/some/path", name="FooPkg", py_version="2.4", platform="win32",
            metadata = Metadata(
                ('PKG-INFO',"Metadata-Version: 1.0\nVersion: 1.3-1\n")
            )
        )
        self.checkFooPkg(d)


    def distDepends(self, txt):
        return Distribution("/foo", metadata=Metadata(('depends.txt', txt)))

    def checkDepends(self, dist, txt, opts=()):
        self.assertEqual(
            list(dist.depends(opts)),
            list(parse_requirements(txt))
        )

    def testDistroDependsSimple(self):
        for v in "Twisted>=1.5", "Twisted>=1.5\nZConfig>=2.0":
            self.checkDepends(self.distDepends(v), v)


    def testResolve(self):
        ad = AvailableDistributions([])

        # Resolving no requirements -> nothing to install
        self.assertEqual( list(ad.resolve([],[])), [] )

        # Request something not in the collection -> DistributionNotFound
        self.assertRaises(
            DistributionNotFound, ad.resolve, parse_requirements("Foo"), []
        )

        Foo = Distribution.from_filename(
            "/foo_dir/Foo-1.2.egg",
            metadata=Metadata(('depends.txt', "[bar]\nBaz>=2.0"))
        )
        ad.add(Foo)

        # Request thing(s) that are available -> list to install
        self.assertEqual(
            list(ad.resolve(parse_requirements("Foo"),[])), [Foo]
        )

        # Request an option that causes an unresolved dependency for "Baz"
        self.assertRaises(
            DistributionNotFound, ad.resolve,parse_requirements("Foo[bar]"),[]
        )      
        Baz = Distribution.from_filename(
            "/foo_dir/Baz-2.1.egg", metadata=Metadata(('depends.txt', "Foo"))
        )
        ad.add(Baz)

        # Install list now includes resolved dependency
        self.assertEqual(
            list(ad.resolve(parse_requirements("Foo[bar]"),[])), [Foo,Baz]
        )
        # Requests for conflicting versions produce VersionConflict
        self.assertRaises(
            VersionConflict,
            ad.resolve, parse_requirements("Foo==1.2\nFoo!=1.2"), []
        )

    def testDistroDependsOptions(self):
        d = self.distDepends("""
            Twisted>=1.5
            [docgen]
            ZConfig>=2.0
            docutils>=0.3
            [fastcgi]
            fcgiapp>=0.1""")
        self.checkDepends(d,"Twisted>=1.5")
        self.checkDepends(
            d,"Twisted>=1.5 ZConfig>=2.0 docutils>=0.3".split(), ["docgen"]
        )
        self.checkDepends(
            d,"Twisted>=1.5 fcgiapp>=0.1".split(), ["fastcgi"]
        )
        self.checkDepends(
            d,"Twisted>=1.5 ZConfig>=2.0 docutils>=0.3 fcgiapp>=0.1".split(),
            ["docgen","fastcgi"]
        )
        self.checkDepends(
            d,"Twisted>=1.5 fcgiapp>=0.1 ZConfig>=2.0 docutils>=0.3".split(),
            ["fastcgi", "docgen"]
        )
        self.assertRaises(InvalidOption, d.depends, ["foo"])

















class RequirementsTests(TestCase):

    def testBasics(self):
        r = Requirement.parse("Twisted>=1.2")
        self.assertEqual(str(r),"Twisted>=1.2")
        self.assertEqual(repr(r),"Requirement('Twisted', [('>=', '1.2')], ())")
        self.assertEqual(r, Requirement("Twisted", [('>=','1.2')]))
        self.assertEqual(r, Requirement("twisTed", [('>=','1.2')]))
        self.assertNotEqual(r, Requirement("Twisted", [('>=','2.0')]))
        self.assertNotEqual(r, Requirement("Zope", [('>=','1.2')]))
        self.assertNotEqual(r, Requirement("Zope", [('>=','3.0')]))
        self.assertNotEqual(r, Requirement.parse("Twisted[extras]>=1.2"))

    def testOrdering(self):
        r1 = Requirement("Twisted", [('==','1.2c1'),('>=','1.2')])
        r2 = Requirement("Twisted", [('>=','1.2'),('==','1.2c1')])
        self.assertEqual(r1,r2)
        self.assertEqual(str(r1),str(r2))
        self.assertEqual(str(r2),"Twisted==1.2c1,>=1.2")

    def testBasicContains(self):
        r = Requirement("Twisted", [('>=','1.2')])
        foo_dist = Distribution.from_filename("FooPkg-1.3_1.egg")
        twist11  = Distribution.from_filename("Twisted-1.1.egg")
        twist12  = Distribution.from_filename("Twisted-1.2.egg")
        self.failUnless(parse_version('1.2') in r)
        self.failUnless(parse_version('1.1') not in r)
        self.failUnless('1.2' in r)
        self.failUnless('1.1' not in r)
        self.failUnless(foo_dist not in r)
        self.failUnless(twist11 not in r)
        self.failUnless(twist12 in r)

    def testAdvancedContains(self):
        r, = parse_requirements("Foo>=1.2,<=1.3,==1.9,>2.0,!=2.5,<3.0,==4.5")
        for v in ('1.2','1.2.2','1.3','1.9','2.0.1','2.3','2.6','3.0c1','4.5'):
            self.failUnless(v in r, (v,r))
        for v in ('1.2c1','1.3.1','1.5','1.9.1','2.0','2.5','3.0','4.0'):
            self.failUnless(v not in r, (v,r))


    def testOptionsAndHashing(self):
        r1 = Requirement.parse("Twisted[foo,bar]>=1.2")
        r2 = Requirement.parse("Twisted[bar,FOO]>=1.2")
        r3 = Requirement.parse("Twisted[BAR,FOO]>=1.2.0")
        self.assertEqual(r1,r2)
        self.assertEqual(r1,r3)
        self.assertEqual(r1.options, ("foo","bar"))
        self.assertEqual(r2.options, ("bar","FOO"))
        self.assertEqual(hash(r1), hash(r2))
        self.assertEqual(
            hash(r1), hash(("twisted", ((">=",parse_version("1.2")),),
                            ImmutableSet(["foo","bar"])))
        )




























class ParseTests(TestCase):

    def testEmptyParse(self):
        self.assertEqual(list(parse_requirements('')), [])

    def testYielding(self):
        for inp,out in [
            ([], []), ('x',['x']), ([[]],[]), (' x\n y', ['x','y']),
            (['x\n\n','y'], ['x','y']),
        ]:
            self.assertEqual(list(pkg_resources.yield_lines(inp)),out)

    def testSplitting(self):
        self.assertEqual(
            list(
                pkg_resources.split_sections("""
                    x
                    [Y]
                    z

                    a
                    [b ]
                    # foo
                    c
                    [ d]
                    [q]
                    v
                    """
                )
            ),
            [(None,["x"]), ("y",["z","a"]), ("b",["c"]), ("d",[]), ("q",["v"])]
        )
        self.assertRaises(ValueError,list,pkg_resources.split_sections("[foo"))








    def testSimpleRequirements(self):
        self.assertEqual(
            list(parse_requirements('Twis-Ted>=1.2-1')),
            [Requirement('Twis-Ted',[('>=','1.2-1')])]
        )
        self.assertEqual(
            list(parse_requirements('Twisted >=1.2, \ # more\n<2.0')),
            [Requirement('Twisted',[('>=','1.2'),('<','2.0')])]
        )
        self.assertEqual(
            Requirement.parse("FooBar==1.99a3"),
            Requirement("FooBar", [('==','1.99a3')])
        )
        self.assertRaises(ValueError,Requirement.parse,">=2.3")
        self.assertRaises(ValueError,Requirement.parse,"x\\")
        self.assertRaises(ValueError,Requirement.parse,"x==2 q")
        self.assertRaises(ValueError,Requirement.parse,"X==1\nY==2")
        self.assertRaises(ValueError,Requirement.parse,"#")


    def testVersionEquality(self):
        def c(s1,s2):
            p1, p2 = parse_version(s1),parse_version(s2)
            self.assertEqual(p1,p2, (s1,s2,p1,p2))

        c('0.4', '0.4.0')
        c('0.4.0.0', '0.4.0')
        c('0.4.0-0', '0.4-0')
        c('0pl1', '0.0pl1')
        c('0pre1', '0.0c1')
        c('0.0.0preview1', '0c1')
        c('0.0c1', '0rc1')









    def testVersionOrdering(self):
        def c(s1,s2):
            p1, p2 = parse_version(s1),parse_version(s2)
            self.failUnless(p1<p2, (s1,s2,p1,p2))

        c('2.1','2.1.1')
        c('2a1','2b0')
        c('2a1','2.1')
        c('2.3a1', '2.3')
        c('2.1-1', '2.1-2')
        c('2.1-1', '2.1.1')
        c('2.1', '2.1pl4')
        c('2.1a0-20040501', '2.1')
        c('1.1', '02.1')
        c('A56','B27')
        c('3.2', '3.2.pl0')
        c('3.2-1', '3.2pl1')
        c('3.2pl1', '3.2pl1-1')
        c('0.4', '4.0')
        c('0.0.4', '0.4.0')
        c('0pl1', '0.4pl1')

        torture ="""
        0.80.1-3 0.80.1-2 0.80.1-1 0.79.9999+0.80.0pre4-1
        0.79.9999+0.80.0pre2-3 0.79.9999+0.80.0pre2-2
        0.77.2-1 0.77.1-1 0.77.0-1
        """.split()

        for p,v1 in enumerate(torture):
            for v2 in torture[p+1:]:
                c(v2,v1)










