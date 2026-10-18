"""Launch installed Serena with per-workspace metadata outside the source tree."""
import hashlib
import os
from pathlib import Path


def prepare(project, data_root):
    project = Path(project).resolve(strict=True)
    data_root = Path(data_root).resolve()
    if data_root.is_relative_to(project):
        # Keel's internal metadata is already outside its audited source surface.
        relative = data_root.relative_to(project)
        if not relative.parts or relative.parts[0] != '.keel':
            raise ValueError('Serena data must be outside source or inside Keel internal metadata')
    key = hashlib.sha256(os.path.normcase(str(project)).encode()).hexdigest()
    home = data_root / key
    home.mkdir(parents=True, exist_ok=True)
    os.environ['SERENA_HOME'] = str(home)
    from serena.config.serena_config import SerenaConfig, ProjectConfig, SerenaPaths
    if Path(SerenaPaths().serena_user_home_dir).resolve() != home:
        raise ValueError('Serena must be initialized in a fresh process for this workspace')
    from ruamel.yaml import YAML
    # Generate the installed version's defaults, then set its documented relocation
    # option. No site-packages patch or audit exclusion is required.
    config = SerenaConfig.from_config_file()
    metadata = home / 'project-data'
    metadata.mkdir(exist_ok=True)  # Prevent fallback to an existing repo/.serena.
    path = home / 'serena_config.yml'
    yaml = YAML()
    data = yaml.load(path.read_text(encoding='utf-8'))
    data['project_serena_folder_location'] = metadata.as_posix()
    with path.open('w', encoding='utf-8') as stream:
        yaml.dump(data, stream)
    config = SerenaConfig.from_config_file()
    if Path(config.get_project_serena_folder(str(project))).resolve() != metadata:
        raise ValueError('Installed Serena did not honor external project metadata location')
    project_file = metadata / 'project.yml'
    if project_file.exists():
        project_config = ProjectConfig.load(str(project), serena_config=config)
    else:
        project_config = ProjectConfig.autogenerate(project, config, asynchronous=False)
    project_config.read_only = True
    project_config.save(str(project_file))
    return home


def launch(executable, data_root, args):
    prepare(Path.cwd(), data_root)
    os.execv(str(executable), [str(executable), *args])
