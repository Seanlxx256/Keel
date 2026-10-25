import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace,ModuleType
import unittest
from unittest.mock import patch

from keel.apt_archive_bridge import (validate_artifact,apply_archive_policy,inject_archive_copy,
    EXPORT_PROGRAM,RESTORE_PROGRAM,install_archive_policy)


def artifact(command='apt-get -y update && apt-get -y upgrade && apt-get install -y unzip'):
    base='sha256:'+'b'*64
    return {'schema_version':1,'image':'keel-apt-archives:'+'a'*32,'image_id':'sha256:'+'c'*64,
        'base_image':'sweb.env.py.x86_64.fixture:latest','base_image_id':base,
        'apt_command_sha256':hashlib.sha256(command.encode()).hexdigest(),
        'cache_id':'keel-apt-'+hashlib.sha256(base.encode()).hexdigest()[:24]}


def harness_modules(make,builder):
    names=['swebench','swebench.harness','swebench.harness.test_spec',
           'swebench.harness.test_spec.test_spec','swebench.harness.docker_build']
    modules={name:ModuleType(name) for name in names}
    for name,module in modules.items():
        module.__path__=[]
        if '.' in name:
            parent,child=name.rsplit('.',1);setattr(modules[parent],child,module)
    modules[names[-2]].make_test_spec=make;modules[names[-1]].build_image=builder
    return modules


class AptArchiveBridgeTests(unittest.TestCase):
    def test_generated_export_context_keeps_python_outside_dockerfile_instructions(self):
        from keel.apt_archive_bridge import export_archives
        value=artifact();seen=[]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);script=root/'setup.sh'
            script.write_text('apt-get -y update && apt-get -y upgrade && apt-get install -y unzip\n')
            diagnosis=root/'diagnosis.json'
            diagnosis.write_text(json.dumps({'status':'apt_completed',
                'source_sha256':hashlib.sha256(script.read_bytes()).hexdigest(),
                'image':value['base_image'],'base_image_id':value['base_image_id'],
                'archive_cache_id':value['cache_id']}))
            def build(command,**kwargs):
                context=Path(command[-1]);lines=(context/'Dockerfile').read_text().splitlines()
                self.assertEqual([line.split()[0] for line in lines],['FROM','COPY','RUN','FROM','COPY'])
                source,destination=lines[1].split()[1:]
                program=(context/source).read_text(encoding='utf-8')
                compile(program,source,'exec')
                self.assertEqual(program,EXPORT_PROGRAM)
                self.assertTrue(lines[2].endswith('python -B '+destination))
                self.assertIn('--network=none',command);seen.append(context)
                return SimpleNamespace(returncode=0)
            with patch('keel.apt_archive_bridge.subprocess.run',return_value=SimpleNamespace(stdout=value['base_image_id'])),patch(
                    'examples.swebench_bridge.run_harness',side_effect=build):
                result=export_archives(diagnosis,script,root/'export')
            self.assertEqual(result['status'],'completed',result)
            self.assertEqual(len(seen),1)

    def spec(self):
        return SimpleNamespace(env_image_key='sweb.env.py.x86_64.fixture:latest',
            repo_script_list=['activate', 'apt-get -y update && apt-get -y upgrade && apt-get install -y unzip',
                              'python -m pip install -e .'],
            eval_script_list=['pytest unchanged'],instance_image_tag='latest')

    def test_recipe_keeps_original_apt_command_tests_and_idempotence(self):
        spec=self.spec();command=spec.repo_script_list[1];value=artifact()
        apply_archive_policy(spec,value)
        self.assertIn(command,spec.repo_script_list)
        self.assertEqual(spec.eval_script_list,['pytest unchanged'])
        before=list(spec.repo_script_list);apply_archive_policy(spec,value)
        self.assertEqual(before,spec.repo_script_list)
        self.assertIn('COPY --from=keel-apt-archives:',inject_archive_copy('FROM env\nRUN setup\n',value))

    def test_workload_base_trap_and_foreign_tag_are_rejected(self):
        for kind in ('workload','base','trap','tag'):
            with self.subTest(kind=kind):
                spec=self.spec();value=artifact()
                if kind=='workload':value['apt_command_sha256']='0'*64
                if kind=='base':spec.env_image_key='another:latest'
                if kind=='trap':spec.repo_script_list.insert(0,'trap original EXIT')
                if kind=='tag':value['image']='foreign:latest'
                with self.assertRaises(ValueError):apply_archive_policy(spec,value)

    def run_programs(self,root):
        cache=root/'cache';cache.mkdir();archives=root/'archives';clean=root/'docker-clean'
        clean.write_bytes(b'original cleanup hook\n')
        (cache/'package_1.0_amd64.deb').write_bytes(b'fixture archive bytes; not an install test')
        program=EXPORT_PROGRAM.replace("'/var/cache/apt/archives'",repr(str(cache))).replace("'/archives'",repr(str(archives)))
        with contextlib.redirect_stdout(io.StringIO()):exec(compile(program,'<export>','exec'),{})
        (cache/'package_1.0_amd64.deb').unlink()
        restore=RESTORE_PROGRAM.replace("'/tmp/keel-apt-archives'",repr(str(archives))).replace(
            "'/var/cache/apt/archives'",repr(str(cache))).replace("'/etc/apt/apt.conf.d/docker-clean'",repr(str(clean)))
        return cache,archives,clean,restore

    def test_real_archive_export_import_cleanup_preserve_bytes_and_hook(self):
        with tempfile.TemporaryDirectory() as temp:
            cache,archives,clean,program=self.run_programs(Path(temp))
            with patch('sys.argv',['probe','before']),contextlib.redirect_stdout(io.StringIO()):
                exec(compile(program,'<import>','exec'),{})
            self.assertEqual((cache/'package_1.0_amd64.deb').read_bytes(),(archives/'package_1.0_amd64.deb').read_bytes())
            self.assertFalse(clean.exists())
            with patch('sys.argv',['probe','after']):exec(compile(program,'<cleanup>','exec'),{})
            self.assertEqual(clean.read_bytes(),b'original cleanup hook\n')
            self.assertEqual(list(cache.iterdir()),[])

    def test_corrupt_archive_or_path_escape_stops_before_cache_mutation(self):
        for kind in ('bytes','path'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as temp:
                cache,archives,clean,program=self.run_programs(Path(temp))
                if kind=='bytes':(archives/'package_1.0_amd64.deb').write_bytes(b'corrupt')
                else:
                    p=archives/'manifest.json';value=json.loads(p.read_text());value['files'][0]['name']='../escape.deb';p.write_text(json.dumps(value))
                with patch('sys.argv',['probe','before']),self.assertRaises(RuntimeError):
                    exec(compile(program,'<import>','exec'),{})
                self.assertEqual(list(cache.iterdir()),[])
                self.assertTrue(clean.exists())

    def test_harness_builder_imports_only_validated_artifact_and_leaves_base_build_alone(self):
        value=artifact();calls=[]
        def make(*a,**k):return self.spec()
        def builder(image_name,setup_scripts,dockerfile,platform,client,build_dir,nocache=False):
            calls.append(dockerfile);return 'built'
        client=SimpleNamespace(api=SimpleNamespace(inspect_image=lambda name:{'Id':
            value['image_id'] if name==value['image'] else value['base_image_id']}))
        modules=harness_modules(make,builder)
        specs=modules['swebench.harness.test_spec.test_spec'];builds=modules['swebench.harness.docker_build']
        with patch.dict(sys.modules,modules):
            install_archive_policy(value)
            spec=specs.make_test_spec({})
            builds.build_image('instance',{'setup_repo.sh':'\n'.join(spec.repo_script_list)},'FROM env\n','linux/amd64',client,Path('context'))
            builds.build_image('base',{},'FROM ubuntu\n','linux/amd64',client,Path('base'))
        self.assertIn('COPY --from=',calls[0]);self.assertEqual(calls[1],'FROM ubuntu\n')

    def test_unknown_artifact_fields_are_not_executable_configuration(self):
        value=artifact();value['command']='unsafe'
        with self.assertRaises(ValueError):validate_artifact(value)

    def test_selfcheck_runner_wires_builder_without_installing_packages(self):
        from examples.check_apt_archive_bridge import execute
        value=artifact();seen=[]
        client=SimpleNamespace(api=SimpleNamespace(build=lambda *a,**k:None,
            inspect_image=lambda name:{'Id':value['image_id'] if name==value['image'] else value['base_image_id']}),
            images=SimpleNamespace(remove=lambda *a,**k:None),close=lambda:None)
        def builder(image_name,setup_scripts,dockerfile,platform,client,build_dir,nocache=False):
            seen.append((setup_scripts,dockerfile))
            (build_dir/'build_image.log').write_text('KEEL_APT_ARCHIVE_BRIDGE='+json.dumps({'injected_files':1,'bytes':42}))
        modules=harness_modules(lambda *a:None,builder)
        modules['docker']=SimpleNamespace(from_env=lambda **k:client)
        with tempfile.TemporaryDirectory() as temp,patch('examples.check_apt_archive_bridge.export_archives',
                return_value={'status':'completed','artifact':value}),patch.dict(sys.modules,modules):
            result=execute(Path('diagnosis'),Path('script'),Path(temp)/'check')
        self.assertEqual(result['status'],'passed')
        self.assertNotIn('apt-get',seen[0][0]['setup_repo.sh'])
        self.assertIn('COPY --from=keel-apt-archives:',seen[0][1])
