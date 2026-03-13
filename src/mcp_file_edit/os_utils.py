import shutil

def check_installed(exe:str):
    # Checks for the 'docker' executable
    docker_path = shutil.which(exe)

    if docker_path:
        return True

    else:
        return False

