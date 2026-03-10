import shutil

def check_installed(exe:str):
    # Checks for the 'docker' executable
    docker_path = shutil.which(exe)

    if docker_path:
        # print(f"{exe} is installed at: {docker_path}")
        return True

    else:
        # print("{exe} is not installed or not in PATH.")
        return False

