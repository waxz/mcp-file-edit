# Derived from mcp-file-edit (MIT, https://github.com/waxz/mcp-file-edit);
# modified for unified-mcp-server. See NOTICE and LICENSE-MIT.
import shutil

def check_installed(exe:str):
    # Checks for the 'docker' executable
    docker_path = shutil.which(exe)

    if docker_path:
        return True

    else:
        return False

