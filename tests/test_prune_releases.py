"""Deletion selectors and fail-closed publication gates; all GitHub calls mocked."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('prune_releases',ROOT/'scripts/prune-releases.py')
prune=importlib.util.module_from_spec(spec)
spec.loader.exec_module(prune)
CURRENT='0.4.0'


def release(version, identifier=100, draft=False):
    names=sorted(prune.installer_names(version))+['SHA256SUMS.txt',f'SHA256SUMS-{version}.txt','source-code.zip','validation.json']
    return {'id':identifier*100,'tag_name':'v'+version,'draft':draft,'assets':[
        {'id':identifier+i,'name':name,'state':'uploaded','size':123,'digest':'sha256:'+'a'*64}
        for i,name in enumerate(names)]}


def package(identifier,*tags):
    return {'id':identifier,'metadata':{'container':{'tags':list(tags)}}}


class PruneSelectorTests(unittest.TestCase):
    def test_releases_only_select_exact_old_installer_and_checksum_assets(self):
        old=release('0.3.0')
        result=prune.release_deletions([old],CURRENT)
        expected=prune.installer_names('0.3.0')|{'SHA256SUMS.txt','SHA256SUMS-0.3.0.txt'}
        self.assertEqual({a['name'] for a in result},expected)
        self.assertEqual(len(result),len(expected))
        self.assertNotIn('source-code.zip',{a['name'] for a in result})
        self.assertNotIn('validation.json',{a['name'] for a in result})

    def test_current_newer_draft_unknown_and_latest_releases_are_protected(self):
        values=[release(CURRENT),release('0.5.0'),release('1.0.0'),release('0.3.0',draft=True),
                {'tag_name':'latest','assets':release('0.3.0')['assets']},
                {'tag_name':'old-nightly','assets':release('0.3.0')['assets']},
                {'assets':release('0.3.0')['assets']}]
        self.assertEqual(prune.release_deletions(values,CURRENT),[])
        # Matching SemVer precedence/build metadata is current, not superseded.
        self.assertEqual(prune.release_deletions([release(CURRENT+'+rebuild')],CURRENT),[])

    def test_invalid_asset_ids_and_mismatched_version_names_are_protected(self):
        value=release('0.3.0')
        name=next(iter(prune.installer_names('0.3.0')))
        value['assets']=[{'id':v,'name':name} for v in (True,False,0,-1,'12',None)]
        value['assets']+=[{'id':99,'name':next(iter(prune.installer_names(CURRENT)))}]
        self.assertEqual(prune.release_deletions([value],CURRENT),[])

    def test_package_aliases_untagged_current_newer_and_latest_are_protected(self):
        values=[package(1,'0.3.0'),package(2,'v0.2.0','0.3.0'),package(3,CURRENT),
                package(4,'0.3.0',CURRENT),package(5,'0.5.0'),package(6,'latest'),
                package(7,'0.3.0','latest'),package(8,'nightly'),package(9),
                package(10,'0.3.0','unknown'),package(11,CURRENT+'+build'),
                package(True,'0.3.0'),package(-1,'0.3.0'),package('12','0.3.0')]
        self.assertEqual(prune.package_deletions(values,CURRENT),[
            {'id':1,'tags':['0.3.0']},{'id':2,'tags':['v0.2.0','0.3.0']}])

    def test_semver_ordering_does_not_use_lexical_order(self):
        values=[package(1,'0.9.0'),package(2,'0.10.0-rc.1'),package(3,'0.10.0'),package(4,'0.11.0')]
        self.assertEqual([v['id'] for v in prune.package_deletions(values,'0.10.0')],[1,2])
        with self.assertRaises(ValueError):prune.package_deletions(values,'not-a-version')


class PruneGateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.report=Path(self.temp.name)/'report.json'
        self.releases=[release('0.3.0',100),release(CURRENT,200)]
        self.packages={p:[package(10,'0.3.0'),package(20,CURRENT),package(30,'latest')]
                       for p in ('windows','linux')}
        self.public={'status':'ok','latestVersion':CURRENT,'assets':{name:'https://example.invalid/'+name for name in prune.ASSET_NAMES}}
        self.calls=[]
        self.fail_path=None

    def tearDown(self):self.temp.cleanup()

    def api(self,path,method='GET',paginated=False):
        self.calls.append((method,path))
        if self.fail_path and self.fail_path in path:
            raise subprocess.CalledProcessError(1,['gh','api',path])
        if method=='DELETE':
            ident=int(path.rsplit('/',1)[-1])
            if '/releases/assets/' in path:
                for rel in self.releases:rel['assets']=[a for a in rel['assets'] if a['id']!=ident]
            else:
                platform='windows' if 'cimc-studio-windows' in path else 'linux'
                self.packages[platform]=[p for p in self.packages[platform] if p['id']!=ident]
            return None
        self.assertEqual(method,'GET')
        if path.startswith('repos/') and '/releases?' in path:return [copy.deepcopy(self.releases)]
        if '/packages/container/cimc-studio-' in path:
            platform='windows' if 'cimc-studio-windows' in path else 'linux'
            return [copy.deepcopy(self.packages[platform])]
        self.fail('Unexpected API call: '+path)

    def invoke(self,execute=True):
        argv=['prune-releases.py','--current-version',CURRENT,'--report',str(self.report)]
        if execute:argv.append('--execute')
        with patch.object(sys,'argv',argv),patch.object(prune,'api',side_effect=self.api),\
             patch.object(prune.UpdateChecker,'check',return_value=self.public),contextlib.redirect_stdout(io.StringIO()):
            prune.main()

    def assert_gate_rejects(self,exception=SystemExit):
        with self.assertRaises(exception):self.invoke()
        self.assertFalse(any(method=='DELETE' for method,_ in self.calls),self.calls)

    def test_missing_current_release_prevents_all_deletion(self):
        self.releases=self.releases[:1]
        self.assert_gate_rejects()

    def test_current_draft_prevents_all_deletion(self):
        self.releases[1]['draft']=True
        self.assert_gate_rejects()

    def test_missing_or_invalid_current_installer_digest_prevents_all_deletion(self):
        baseline=copy.deepcopy(self.releases)
        for mutation in ('missing','digest','state','empty'):
            with self.subTest(mutation=mutation):
                self.releases=copy.deepcopy(baseline);self.calls=[]
                asset=self.releases[1]['assets'][0]
                if mutation=='missing':self.releases[1]['assets'].pop(0)
                elif mutation=='digest':asset['digest']='sha256:not-a-digest'
                elif mutation=='state':asset['state']='new'
                else:asset['size']=0
                self.assert_gate_rejects()

    def test_public_update_source_must_identify_complete_current_version(self):
        baseline=copy.deepcopy(self.public)
        for mutation in ('network','old','asset'):
            with self.subTest(mutation=mutation):
                self.public=copy.deepcopy(baseline);self.calls=[]
                if mutation=='network':self.public['status']='error'
                elif mutation=='old':self.public['latestVersion']='0.3.0'
                else:self.public['assets']['html']=None
                self.assert_gate_rejects()

    def test_missing_current_package_on_either_platform_prevents_all_deletion(self):
        for platform in ('windows','linux'):
            with self.subTest(platform=platform):
                original=self.packages[platform];self.packages[platform]=[package(10,'0.3.0')];self.calls=[]
                self.assert_gate_rejects()
                self.packages[platform]=original

    def test_package_inventory_failure_prevents_earlier_release_deletions(self):
        self.fail_path='cimc-studio-linux'
        self.assert_gate_rejects(subprocess.CalledProcessError)
        self.assertTrue(any('cimc-studio-windows' in path for _,path in self.calls))

    def test_dry_run_produces_plan_without_deleting(self):
        self.invoke(execute=False)
        self.assertFalse(any(method=='DELETE' for method,_ in self.calls))
        report=json.loads(self.report.read_text(encoding='utf-8'))
        self.assertFalse(report['executed']);self.assertFalse(report['verified'])
        self.assertEqual(report['deleted'],[])
        self.assertTrue(report['releaseAssets'])

    def test_execute_deletes_only_planned_old_ids_and_verifies_remaining(self):
        old_ids={a['id'] for a in prune.release_deletions(self.releases,CURRENT)}
        current_before=copy.deepcopy(self.releases[1])
        self.invoke()
        deleted=[path for method,path in self.calls if method=='DELETE']
        release_ids={int(p.rsplit('/',1)[-1]) for p in deleted if '/releases/assets/' in p}
        self.assertEqual(release_ids,old_ids)
        self.assertEqual(len(deleted),len(old_ids)+2)
        self.assertEqual(self.releases[1],current_before)
        for platform in self.packages:self.assertEqual([p['id'] for p in self.packages[platform]],[20,30])
        report=json.loads(self.report.read_text(encoding='utf-8'))
        self.assertTrue(report['executed']);self.assertTrue(report['verified'])
        self.assertEqual(len(report['deleted']),len(deleted))

    def test_changed_current_installer_after_cleanup_is_not_marked_verified(self):
        original_api=self.api
        def changed_inventory(path,method='GET',paginated=False):
            result=original_api(path,method,paginated)
            if method=='GET' and '/releases?' in path and any(m=='DELETE' for m,_ in self.calls):
                current=next(r for r in result[0] if r['tag_name']=='v'+CURRENT)
                current['assets'][0]['digest']='sha256:'+'b'*64
            return result
        with patch.object(self,'api',side_effect=changed_inventory):
            with self.assertRaises(AssertionError):self.invoke()
        report=json.loads(self.report.read_text(encoding='utf-8'))
        self.assertFalse(report['verified'])
        self.assertTrue(report['deleted'])


if __name__=='__main__':unittest.main()
