# Windows Development Environment

## Python Execution

### Conda Environment
BoundState uses the `boundstate-intent` conda environment. When running Python:

```bash
# PREFERRED: Use conda run to ensure correct environment
conda run -n boundstate-intent python script.py

# OR: Activate first then run
conda activate boundstate-intent && python script.py

# OR: Use full path to conda Python
/c/Users/jwilde2/.conda/envs/boundstate-intent/python.exe script.py
```

### Common Issues

1. **Stale file shadowing Python**: If a file named `python` exists in the working directory, Git Bash will find it before the actual Python executable. Delete any such files.

2. **Path translation**: Git Bash uses Unix-style paths. Use `/c/BoundState/` not `C:\BoundState\` in bash commands.

3. **Inline Python (`python -c`)**: Complex multiline code often fails due to quote handling. Write a script file instead.

### Running Scripts
```bash
# BEST: Use py launcher (always works on Windows)
py /c/BoundState/scripts/my_script.py

# Run pytest with py launcher
py -m pytest /c/BoundState/tests/ -v

# Run with output
py -u /c/BoundState/scripts/my_script.py  # -u for unbuffered output
```

### The `py` Launcher (Recommended)
On Windows, always prefer `py` over `python` in Git Bash:
- `py` is the Windows Python Launcher - it always finds Python correctly
- `python` depends on PATH which can be misconfigured in Git Bash
- `py -3.11` to specify a version

### Working Directory
The default working directory is `C:\BoundState`. Always use absolute paths for reliability.

## Path Conventions

| Context | Format | Example |
|---------|--------|---------|
| Git Bash | Unix-style | `/c/BoundState/mira/` |
| Python | Either works | `C:\\BoundState\\mira\\` or `C:/BoundState/mira/` |
| Windows CMD | Backslashes | `C:\BoundState\mira\` |

## File Operations

### Reading Files
Use the Read tool instead of `cat` - it handles Windows paths correctly.

### Creating Files
Use the Write tool instead of `echo >` or heredocs - avoids encoding issues.

## Testing

```bash
# Use the conda Python directly for pytest
CONDA_PYTHON=/c/Users/jwilde2/.conda/envs/boundstate-intent/python.exe

# Run all tests
$CONDA_PYTHON -m pytest /c/BoundState/tests/ -v

# Run specific test file
$CONDA_PYTHON -m pytest /c/BoundState/tests/mira/test_h2_knowledge_twin_automated.py -v

# Run with coverage
$CONDA_PYTHON -m pytest /c/BoundState/tests/ --cov=mira --cov-report=term-missing

# One-liner (copy-paste ready)
/c/Users/jwilde2/.conda/envs/boundstate-intent/python.exe -m pytest /c/BoundState/tests/ -v --tb=short
```

## Common Commands

```bash
# Use conda Python for all commands
CONDA_PYTHON=/c/Users/jwilde2/.conda/envs/boundstate-intent/python.exe

# Check Python version
$CONDA_PYTHON --version

# List conda environments
conda env list

# Install package in environment
$CONDA_PYTHON -m pip install package-name

# Run a script
$CONDA_PYTHON /c/BoundState/scripts/my_script.py

# Check what Python is being used
which python  # Often wrong in Git Bash
echo $CONDA_PYTHON  # Use this instead
```

## Known Issues

### Git Bash PATH Problems
The `python` command in Git Bash may not use the conda environment. Always use the full path:
```bash
/c/Users/jwilde2/.conda/envs/boundstate-intent/python.exe
```

### py Launcher Limitation
The `py` launcher finds Python but may use a different environment (e.g., system Python 3.11 without packages). Use the conda path for tests requiring installed packages.
