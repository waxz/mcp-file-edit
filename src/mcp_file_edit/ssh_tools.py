"""
SSH operations tools for MCP file editor
"""

import os
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional

from .file_operations import LocalFileOperations
from .ssh_manager import SSHConnectionManager
from .utils import (
    FILE_OPS, PROJECT_DIR, SSH_MANAGER, CONNECTION_TYPE,
    BASE_DIR, resolve_path
)


# Tool functions that will be registered with FastMCP

async def ssh_upload(
    local_path: str,
    remote_path: str,
    recursive: bool = False,
    overwrite: bool = True
) -> Dict[str, Any]:
    """
    Upload file(s) from local filesystem to remote SSH server.
    
    Args:
        local_path: Local file or directory path to upload
        remote_path: Remote destination path (on SSH server)
        recursive: Upload directories recursively
        overwrite: Overwrite existing files on remote
        
    Returns:
        Dictionary with upload results
    """
    if CONNECTION_TYPE != "ssh":
        raise ValueError("SSH connection not established. Use set_project_directory with connection_type='ssh' first")
    
    # Ensure we have local file operations for reading
    local_ops = LocalFileOperations()
    
    # Parse paths
    local_path_obj = Path(local_path).resolve()
    remote_path_obj = Path(remote_path)
    
    # If remote path is relative, make it relative to PROJECT_DIR
    if not remote_path_obj.is_absolute():
        remote_path_obj = PROJECT_DIR / remote_path_obj
    
    # Check if local path exists
    if not await local_ops.exists(local_path_obj):
        raise ValueError(f"Local path does not exist: {local_path}")
    
    uploaded_files = []
    errors = []
    
    try:
        if await local_ops.is_file(local_path_obj):
            # Upload single file
            try:
                # Check if remote path exists and is a directory
                remote_exists = await FILE_OPS.exists(remote_path_obj)
                if remote_exists and await FILE_OPS.is_dir(remote_path_obj):
                    # If remote is a directory, use same filename
                    remote_file_path = remote_path_obj / local_path_obj.name
                else:
                    # Use remote path as-is
                    remote_file_path = remote_path_obj
                
                # Check if should overwrite
                if await FILE_OPS.exists(remote_file_path) and not overwrite:
                    errors.append({
                        "file": str(local_path_obj),
                        "error": f"Remote file exists and overwrite=False: {remote_file_path}"
                    })
                else:
                    # Read local file
                    content = await local_ops.read(local_path_obj)
                    
                    # Write to remote
                    await FILE_OPS.write(remote_file_path, content)
                    
                    uploaded_files.append({
                        "local": str(local_path_obj),
                        "remote": str(remote_file_path),
                        "size": len(content)
                    })
            except Exception as e:
                errors.append({
                    "file": str(local_path_obj),
                    "error": str(e)
                })
        
        elif await local_ops.is_dir(local_path_obj):
            if not recursive:
                raise ValueError("Directory upload requires recursive=True")
            
            # Create remote directory if it doesn't exist
            if not await FILE_OPS.exists(remote_path_obj):
                await FILE_OPS.makedirs(remote_path_obj)
            
            # Walk through local directory
            for root, dirs, files in os.walk(local_path_obj):
                root_path = Path(root)
                rel_path = root_path.relative_to(local_path_obj)
                
                # Create directories on remote
                for dir_name in dirs:
                    remote_dir = remote_path_obj / rel_path / dir_name
                    try:
                        if not await FILE_OPS.exists(remote_dir):
                            await FILE_OPS.makedirs(remote_dir)
                    except Exception as e:
                        errors.append({
                            "file": str(root_path / dir_name),
                            "error": f"Failed to create remote directory: {e}"
                        })
                
                # Upload files
                for file_name in files:
                    local_file = root_path / file_name
                    remote_file = remote_path_obj / rel_path / file_name
                    
                    try:
                        if await FILE_OPS.exists(remote_file) and not overwrite:
                            errors.append({
                                "file": str(local_file),
                                "error": f"Remote file exists and overwrite=False: {remote_file}"
                            })
                            continue
                        
                        # Read local file
                        content = await local_ops.read(local_file)
                        
                        # Write to remote
                        await FILE_OPS.write(remote_file, content)
                        
                        uploaded_files.append({
                            "local": str(local_file),
                            "remote": str(remote_file),
                            "size": len(content)
                        })
                    except Exception as e:
                        errors.append({
                            "file": str(local_file),
                            "error": str(e)
                        })
    
    except Exception as e:
        raise ValueError(f"Upload failed: {str(e)}")
    
    return {
        "uploaded": len(uploaded_files),
        "errors": len(errors),
        "files": uploaded_files,
        "error_details": errors,
        "total_size": sum(f["size"] for f in uploaded_files)
    }


async def ssh_download(
    remote_path: str,
    local_path: str,
    recursive: bool = False,
    overwrite: bool = True
) -> Dict[str, Any]:
    """
    Download file(s) from remote SSH server to local filesystem.
    
    Args:
        remote_path: Remote file or directory path to download (on SSH server)
        local_path: Local destination path
        recursive: Download directories recursively
        overwrite: Overwrite existing local files
        
    Returns:
        Dictionary with download results
    """
    if CONNECTION_TYPE != "ssh":
        raise ValueError("SSH connection not established. Use set_project_directory with connection_type='ssh' first")
    
    # Ensure we have local file operations for writing
    local_ops = LocalFileOperations()
    
    # Parse paths
    local_path_obj = Path(local_path).resolve()
    remote_path_obj = Path(remote_path)
    
    # If remote path is relative, make it relative to PROJECT_DIR
    if not remote_path_obj.is_absolute():
        remote_path_obj = PROJECT_DIR / remote_path_obj
    
    # Check if remote path exists
    if not await FILE_OPS.exists(remote_path_obj):
        raise ValueError(f"Remote path does not exist: {remote_path}")
    
    downloaded_files = []
    errors = []
    
    try:
        if await FILE_OPS.is_file(remote_path_obj):
            # Download single file
            try:
                # Check if local path exists and is a directory
                local_exists = await local_ops.exists(local_path_obj)
                if local_exists and await local_ops.is_dir(local_path_obj):
                    # If local is a directory, use same filename
                    local_file_path = local_path_obj / remote_path_obj.name
                else:
                    # Use local path as-is
                    local_file_path = local_path_obj
                
                # Check if should overwrite
                if await local_ops.exists(local_file_path) and not overwrite:
                    errors.append({
                        "file": str(remote_path_obj),
                        "error": f"Local file exists and overwrite=False: {local_file_path}"
                    })
                else:
                    # Ensure parent directory exists
                    local_file_path.parent.mkdir(parents=True, exist_ok=True)
                    
                    # Read remote file
                    content = await FILE_OPS.read(remote_path_obj)
                    
                    # Write to local
                    await local_ops.write(local_file_path, content)
                    
                    downloaded_files.append({
                        "remote": str(remote_path_obj),
                        "local": str(local_file_path),
                        "size": len(content)
                    })
            except Exception as e:
                errors.append({
                    "file": str(remote_path_obj),
                    "error": str(e)
                })
        
        elif await FILE_OPS.is_dir(remote_path_obj):
            if not recursive:
                raise ValueError("Directory download requires recursive=True")
            
            # Create local directory if it doesn't exist
            local_path_obj.mkdir(parents=True, exist_ok=True)
            
            # List and download directory contents recursively
            async def download_dir(remote_dir: Path, local_dir: Path):
                # List remote directory contents
                entries = await FILE_OPS.listdir(remote_dir)
                
                for entry in entries:
                    remote_entry = remote_dir / entry
                    local_entry = local_dir / entry
                    
                    try:
                        if await FILE_OPS.is_dir(remote_entry):
                            # Create local directory
                            local_entry.mkdir(exist_ok=True)
                            # Recursively download subdirectory
                            await download_dir(remote_entry, local_entry)
                        else:
                            # Download file
                            if await local_ops.exists(local_entry) and not overwrite:
                                errors.append({
                                    "file": str(remote_entry),
                                    "error": f"Local file exists and overwrite=False: {local_entry}"
                                })
                                continue
                            
                            # Read remote file
                            content = await FILE_OPS.read(remote_entry)
                            
                            # Write to local
                            await local_ops.write(local_entry, content)
                            
                            downloaded_files.append({
                                "remote": str(remote_entry),
                                "local": str(local_entry),
                                "size": len(content)
                            })
                    except Exception as e:
                        errors.append({
                            "file": str(remote_entry),
                            "error": str(e)
                        })
            
            await download_dir(remote_path_obj, local_path_obj)
    
    except Exception as e:
        raise ValueError(f"Download failed: {str(e)}")
    
    return {
        "downloaded": len(downloaded_files),
        "errors": len(errors),
        "files": downloaded_files,
        "error_details": errors,
        "total_size": sum(f["size"] for f in downloaded_files)
    }


async def ssh_sync(
    local_path: str,
    remote_path: str,
    direction: str = "upload",
    delete: bool = False,
    exclude_patterns: Optional[List[str]] = None,
    update_only: bool = True,
    show_progress: bool = True
) -> Dict[str, Any]:
    """
    Synchronize files between local and remote filesystems using rsync.
    
    Args:
        local_path: Local directory path
        remote_path: Remote directory path (on SSH server)
        direction: Sync direction - "upload" (local to remote) or "download" (remote to local)
        delete: Delete files in destination that don't exist in source
        exclude_patterns: List of glob patterns to exclude from sync
        update_only: Only replace files if source files are newer (default: True)
        show_progress: Show rsync progress output (default: True)
        
    Returns:
        Dictionary with sync results
    """
    if CONNECTION_TYPE != "ssh":
        raise ValueError("SSH connection not established. Use set_project_directory with connection_type='ssh' first")
    
    if direction not in ["upload", "download"]:
        raise ValueError("Direction must be 'upload' or 'download'")
    
    # Get SSH connection details from SSH_MANAGER
    if not SSH_MANAGER.host or not SSH_MANAGER.username:
        raise ValueError("SSH host and username not configured")
    
    # Build rsync command
    rsync_cmd = ["rsync", "-avz"]  # archive, verbose, compress
    
    # Add update flag if requested (only update files if source is newer)
    if update_only:
        rsync_cmd.append("-u")
    
    # Add progress flag if requested
    if show_progress:
        rsync_cmd.append("--progress")
    
    # Add delete flag if requested
    if delete:
        rsync_cmd.append("--delete")
    
    # Add exclude patterns
    if exclude_patterns:
        for pattern in exclude_patterns:
            rsync_cmd.extend(["--exclude", pattern])
    
    # Add SSH options
    ssh_options = f"-p {SSH_MANAGER.port}"
    if SSH_MANAGER.key_filename:
        ssh_options += f" -i {SSH_MANAGER.key_filename}"
    rsync_cmd.extend(["-e", f"ssh {ssh_options}"])
    
    # Build source and destination paths
    if direction == "upload":
        # Ensure local path ends with / for directory sync
        if not local_path.endswith('/'):
            local_path += '/'
        source = local_path
        destination = f"{SSH_MANAGER.username}@{SSH_MANAGER.host}:{remote_path}"
    else:  # download
        # Ensure remote path ends with / for directory sync
        if not remote_path.endswith('/'):
            remote_path += '/'
        source = f"{SSH_MANAGER.username}@{SSH_MANAGER.host}:{remote_path}"
        destination = local_path
    
    rsync_cmd.extend([source, destination])
    
    # Execute rsync command
    import sys
    
    try:
        # Create subprocess
        process = await asyncio.create_subprocess_exec(
            *rsync_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # Collect output with progress indication
        stdout_data = []
        stderr_data = []
        
        # Read stdout and stderr concurrently
        async def read_stream(stream, data_list, is_progress=False):
            while True:
                line = await stream.readline()
                if not line:
                    break
                decoded_line = line.decode('utf-8', errors='ignore')
                data_list.append(decoded_line)
                
                # Print progress lines to give feedback
                if show_progress and is_progress:
                    # Only print lines that contain progress info
                    if '%' in decoded_line or 'to-check=' in decoded_line:
                        print(f"\rProgress: {decoded_line.strip()}", end='', file=sys.stderr)
        
        # Start reading both streams
        await asyncio.gather(
            read_stream(process.stdout, stdout_data, is_progress=True),
            read_stream(process.stderr, stderr_data)
        )
        
        # Wait for process to complete
        returncode = await process.wait()
        
        # Clear progress line
        if show_progress:
            print("\r" + " " * 80 + "\r", end='', file=sys.stderr)
        
        stdout = ''.join(stdout_data)
        stderr = ''.join(stderr_data)
        
        if returncode != 0:
            raise RuntimeError(f"rsync failed with return code {returncode}: {stderr}")
        
        # Parse rsync output to get statistics
        files_transferred = 0
        total_size = 0
        
        # Look for summary statistics in output
        for line in stdout_data:
            # Match lines like "Number of files transferred: X"
            if "Number of files transferred:" in line:
                try:
                    files_transferred = int(line.split(':')[-1].strip())
                except:
                    pass
            # Match lines like "Total transferred file size: X bytes"
            elif "Total transferred file size:" in line:
                try:
                    size_str = line.split(':')[-1].strip()
                    # Remove "bytes" and convert
                    total_size = int(size_str.replace('bytes', '').replace(',', '').strip())
                except:
                    pass
        
        # Also parse file list from verbose output
        transferred_files = []
        for line in stdout_data:
            # rsync verbose output shows transferred files
            # Skip directory entries and summary lines
            if line.strip() and not line.startswith('sending') and not line.startswith('sent') \
               and not line.startswith('total') and not line.endswith('/'):
                # Clean up the line
                file_path = line.strip()
                if file_path and not any(skip in file_path for skip in ['Number of', 'Total', 'building']):
                    transferred_files.append(file_path)
        
        return {
            "success": True,
            "direction": direction,
            "source": source,
            "destination": destination,
            "files_transferred": files_transferred,
            "total_size": total_size,
            "transferred_files": transferred_files[:100],  # Limit to first 100 files
            "rsync_command": ' '.join(rsync_cmd),
            "stdout": stdout[-1000:] if len(stdout) > 1000 else stdout,  # Last 1000 chars
            "stderr": stderr
        }
        
    except Exception as e:
        return {
            "success": False,
            "direction": direction,
            "error": str(e),
            "rsync_command": ' '.join(rsync_cmd)
        }
