"""Utility functions and validators"""
import yaml
import logging
import platform
import shutil
import re
from pathlib import Path
from typing import List, Dict, Optional, Union
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from questionary import Validator, ValidationError, select, checkbox, text, confirm
import subprocess
import json
import gzip

logger = logging.getLogger(__name__)
console = Console()

# Get project root
PROJECT_ROOT = Path(__file__).parent.parent.parent
USER_ADAPTERS_DIR = PROJECT_ROOT / "adapters" / "user_adapters"
USER_ADAPTERS_DIR.mkdir(parents=True, exist_ok=True)

class PathValidator(Validator):
    def validate(self, document):
        if not document.text:
            raise ValidationError(message="Please enter a path", cursor_position=len(document.text))
        path = Path(document.text)
        if not path.exists():
            raise ValidationError(message="Path does not exist", cursor_position=len(document.text))

class YamlValidator(Validator):
    def validate(self, document):
        if not document.text:
            raise ValidationError(message="Please enter YAML content", cursor_position=len(document.text))
        try:
            yaml.safe_load(document.text)
        except yaml.YAMLError as e:
            raise ValidationError(message=f"Invalid YAML: {str(e)}", cursor_position=len(document.text))

class PythonClassValidator(Validator):
    def validate(self, document):
        if not document.text:
            raise ValidationError(message="Please enter a valid Python class name", cursor_position=len(document.text))
        if not re.match(r'^[A-Z][a-zA-Z0-9]*$', document.text):
            raise ValidationError(message="Class name must be PascalCase", cursor_position=len(document.text))

def find_config_files(organism: str = None) -> Dict[str, str]:
    config_dir = PROJECT_ROOT / "config"
    files = {
        "Human - Sample Adapters": str(config_dir / "adapters_config_sample.yaml"),
        "Human - Full Adapters": str(config_dir / "adapters_config.yml"),
        "Fly - Sample Adapters": str(config_dir / "dmel_adapters_config_sample.yaml"),
        "Fly - Full Adapters": str(config_dir / "dmel_adapters_config.yml"),
        "Biocypher Config": str(config_dir / "biocypher_config.yml"),
        "Docker Config": str(config_dir / "biocypher_docker_config.yml"),
        "Data Source Config": str(config_dir / "data_source_config.yml"),
        "Download Config": str(config_dir / "download.yml"),
    }
    if organism == "human":
        return {k: v for k, v in files.items() if k.startswith("Human") or "Config" in k}
    elif organism == "fly":
        return {k: v for k, v in files.items() if k.startswith("Fly") or "Config" in k}
    return files

def find_aux_files(organism: str = None) -> Dict[str, str]:
    aux_dir = PROJECT_ROOT / "aux_files"
    files = {
        "Human - Tissues Ontology Map": str(aux_dir / "abc_tissues_to_ontology_map.pkl"),
        "Human - dbSNP rsIDs": str(aux_dir / "sample_dbsnp_rsids.pkl"),
        "Human - dbSNP Positions": str(aux_dir / "sample_dbsnp_pos.pkl"),
        "Human - Gene Mapping": str(aux_dir / "gene_mapping.pkl"),
        "Human - Variant Data": str(aux_dir / "variant_data.pkl"),
        "Fly - dbSNP rsIDs": str(aux_dir / "sample_dbsnp_rsids.pkl"),
        "Fly - dbSNP Positions": str(aux_dir / "sample_dbsnp_pos.pkl"),
    }
    if organism == "human":
        return {k: v for k, v in files.items() if k.startswith("Human")}
    elif organism == "fly":
        return {k: v for k, v in files.items() if k.startswith("Fly")}
    return files

def get_available_adapters(config_path: str) -> List[str]:
    try:
        with open(config_path) as f:
            config = yaml.safe_load(f)
            if not config: return []
            adapters = []
            for key, value in config.items():
                if isinstance(value, dict) and ('adapter' in value or 'module' in value):
                    adapters.append(key)
                else:
                    adapters.append(key)
            return sorted(adapters)
    except Exception as e:
        logger.error(f"Error loading adapters from {config_path}: {e}")
        return []

def get_file_selection(prompt: str, options: Dict[str, str], allow_multiple: bool = True, allow_custom: bool = True, back_option: bool = True):
    choices = list(options.keys())
    if allow_custom: choices.append("📤 Enter custom path")
    if back_option: choices.append("🔙 Back")
    
    while True:
        if allow_multiple:
            selected = checkbox(prompt, choices=choices, instruction="(Use space to select, enter to confirm)").unsafe_ask()
        else:
            selected = select(prompt, choices=choices).unsafe_ask()
        
        if selected == "🔙 Back": return None
        if not isinstance(selected, list): selected = [selected]
        
        result = []
        for item in selected:
            if item == "📤 Enter custom path":
                custom_path = text("Please enter the full path:", validate=PathValidator).unsafe_ask()
                if custom_path: result.append(custom_path)
            elif item != "🔙 Back":
                result.append(options[item])
        
        if result: return result if allow_multiple else result[0]

def display_config_summary(config: Dict[str, Union[str, List[str]]]) -> None:
    table = Table(title="\nConfiguration Summary", show_header=True, header_style="bold magenta")
    table.add_column("Option", style="cyan"); table.add_column("Value", style="green")
    for key, value in config.items():
        if isinstance(value, list): value = ", ".join(value)
        table.add_row(key, str(value))
    console.print(Panel.fit(table, style="blue"))

def view_system_status() -> None:
    table = Table(title="System Status", show_header=True)
    table.add_column("Component", style="cyan"); table.add_column("Status", style="green")
    required_dirs = [PROJECT_ROOT / "config", PROJECT_ROOT / "aux_files", USER_ADAPTERS_DIR]
    for d in required_dirs:
        status = "✅ Found" if d.exists() else "❌ Missing"
        table.add_row(str(d), status)
    table.add_row("Python Version", platform.python_version())
    total, used, free = shutil.disk_usage("/")
    table.add_row("Disk Space", f"Total: {total // (2**30)}GB, Free: {free // (2**30)}GB")
    console.print(Panel.fit(table))

def show_help() -> None:
    help_text = """
    [bold]BioCypher Knowledge Graph Generator Help[/]
    [underline]Main Features:[/]
    - 🚀 Generate knowledge graphs for Human or Drosophila melanogaster
    - ⚡ Quick start with default configurations
    - 🛠️ Full customization options for advanced users
    - 🐍 Create custom adapters through CLI
    [underline]Workflow:[/]
    1. Select organism (Human or Fly)
    2. Choose default or custom configuration
    3. For custom: Configure each parameter
    4. Review configuration summary
    5. Execute generation
    [underline]Custom Adapters:[/]
    - Create new adapters in adapters/user_adapters/
    - Choose between writing from scratch or using templates
    - Automatically generates config entries
    [underline]Navigation:[/]
    - Use arrow keys to move between options
    - Press Enter to confirm selections
    - Most screens support going back with the '🔙 Back' option
    [underline]Troubleshooting:[/]
    - Ensure all required directories exist
    - Check file permissions if you encounter errors
    - Use the detailed logs option to diagnose problems
    """
    console.print(Panel.fit(help_text, title="Help & Documentation"))



def check_and_prepare_samples(adapters_config_path: str, selected_adapters: List[str] = None, limit: int = 100) -> List[str]:
    """Ensure sample files referenced by the adapters config exist.
    If a sample is missing, attempt to find a download URL in `config/data_source_config.yaml`
    and run `scripts/download_and_sample.py` to create a sampled file. Returns list of created files.
    """
    created = []
    try:
        config_path = Path(adapters_config_path)
        if not config_path.exists():
            console.print(f"[yellow]Adapters config not found: {config_path}[/]")
            return created
        with open(config_path) as f:
            adapters = yaml.safe_load(f) or {}
    except Exception as e:
        console.print(f"[red]Failed to read adapters config: {e}[/]")
        return created

    data_source = {}
    try:
        ds_path = PROJECT_ROOT / "config" / "data_source_config.yaml"
        if ds_path.exists():
            with open(ds_path) as f:
                data_source = yaml.safe_load(f) or {}
    except Exception:
        data_source = {}

    def _is_file_sane(path: Path) -> (bool, str):
        """Level-1 file sanity checks: size>0 and at least one non-blank line.
        Supports plain text and gzip (.gz) files.
        Returns (True, "") when sane, or (False, reason).
        """
        try:
            if not path.exists():
                return False, "file missing"

            if path.is_dir():
                for child in path.rglob('*'):
                    if child.is_file():
                        sane, reason = _is_file_sane(child)
                        if sane:
                            return True, "directory contains at least one sane file"
                return False, "directory contains no sane files"

            size = path.stat().st_size
            if size == 0:
                return False, "file size is 0 bytes"

            open_fn = gzip.open if path.suffix == ".gz" else open
            with open_fn(path, "rt", errors="ignore") as fh:
                for line in fh:
                    if line.strip():
                        return True, ""
            return False, "no non-blank lines found"
        except Exception as e:
            return False, f"exception while validating file: {e}"

    for name, conf in (adapters.items() if isinstance(adapters, dict) else []):
        if selected_adapters and name not in selected_adapters:
            continue
        args = {}
        try:
            args = conf.get("adapter", {}).get("args", {}) or {}
        except Exception:
            args = {}

        file_fields = []
        for k, v in args.items():
            if isinstance(v, str) and ("samples" in v or k.lower().find("file") != -1 or k.lower().find("path") != -1):
                file_fields.append(v)

        for fp in file_fields:
            out_path = Path(fp)
            if not out_path.is_absolute():
                out_path = PROJECT_ROOT / out_path

            if out_path.exists():
                sane, reason = _is_file_sane(out_path)
                if sane:
                    continue
                else:
                    console.print(f"[yellow]Existing sample {out_path} failed sanity check: {reason}. Will attempt to recreate.[/]")

            basename = Path(fp).name
            url = None

           
            name_no_ext = basename.split('.')[0]
            tokens = re.split(r'[-_.]+', name_no_ext)
            candidates_set = set()
            candidates_set.add(name_no_ext)
            candidates_set.add(name_no_ext.replace('-', '_'))

            for end in range(len(tokens), 0, -1):
                prefix_tokens = tokens[:end]
                if not prefix_tokens:
                    continue
                candidates_set.add('_'.join(prefix_tokens))
                candidates_set.add('-'.join(prefix_tokens))
                candidates_set.add(''.join(prefix_tokens))

            if tokens:
                candidates_set.add(tokens[0])

            candidates = [c.lower().strip('_-') for c in candidates_set if c]
            candidates = sorted(dict.fromkeys(candidates), key=lambda s: (-len(s), s))

            for k in candidates:
                if not k: continue
                if k in data_source:
                    entry = data_source[k]
                    url_field = entry.get("url") if isinstance(entry, dict) else entry
                    if isinstance(url_field, list):
                        url = url_field[0]
                    elif isinstance(url_field, dict):
                        vals = list(url_field.values())
                        url = vals[0] if vals else None
                    else:
                        url = url_field
                    break

            if not url:
                for ds_key in data_source.keys():
                    if ds_key in name_no_ext or name_no_ext.startswith(ds_key) or ds_key.startswith(name_no_ext):
                        entry = data_source[ds_key]
                        url_field = entry.get("url") if isinstance(entry, dict) else entry
                        if isinstance(url_field, list):
                            url = url_field[0]
                        elif isinstance(url_field, dict):
                            vals = list(url_field.values())
                            url = vals[0] if vals else None
                        else:
                            url = url_field
                        break

            if not url:
                console.print(Panel.fit(f"[yellow]Sample for adapter '{name}' is missing: {out_path}[/]"))
                inp = text(f"Enter input URL or local path to download for '{name}' (leave blank to skip):")
                val = inp.unsafe_ask()
                if not val:
                    console.print(f"[dim]Skipping adapter {name} (no input provided).[/]")
                    continue
                url = val

            # run download_and_sample.py
            cmd = ["python3", str(PROJECT_ROOT / "scripts" / "download_and_sample.py"), "--input", str(url), "--output", str(out_path), "--limit", str(limit)]
            console.print(Panel.fit(f"[blue]Preparing sample for '{name}' by running download_and_sample.py[/]"))
            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=str(PROJECT_ROOT))
                for line in proc.stdout:
                    console.print(f"[dim]{line.rstrip()}[/]")
                proc.wait()

                def _handle_result(returncode, out_path, attempt_url):
                    if returncode == 0 and out_path.exists():
                        sane, reason = _is_file_sane(out_path)
                        if sane:
                            console.print(f"[green]Wrote sample file: {out_path}[/]")
                            created.append(str(out_path))
                            return True
                        else:
                            console.print(f"[red]Sample created but failed sanity check ({reason}): {out_path}[/]")
                            return False
                    else:
                        console.print(f"[red]Failed to create sample for adapter {name} using {attempt_url}[/]")
                        return False

                success = _handle_result(proc.returncode, out_path, url)
                if not success:
                   
                    alt_inp = text(f"Enter alternate input URL or local path for '{name}' (leave blank to skip):")
                    alt_val = alt_inp.unsafe_ask()
                    if not alt_val:
                        console.print(f"[dim]Skipping adapter {name} (no alternative provided).[/]")
                    else:
                        retry_cmd = ["python3", str(PROJECT_ROOT / "scripts" / "download_and_sample.py"), "--input", str(alt_val), "--output", str(out_path), "--limit", str(limit)]
                        console.print(Panel.fit(f"[blue]Retrying sample preparation for '{name}' with provided input[/]"))
                        try:
                            proc2 = subprocess.Popen(retry_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=str(PROJECT_ROOT))
                            for line in proc2.stdout:
                                console.print(f"[dim]{line.rstrip()}[/]")
                            proc2.wait()
                            _handle_result(proc2.returncode, out_path, alt_val)
                        except Exception as e:
                            console.print(f"[red]Retry failed for {name}: {e}[/]")
            except Exception as e:
                console.print(f"[red]Error running download_and_sample for {name}: {e}[/]")

    return created