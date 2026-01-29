"""
SSH Client Implementation

Provides SSH connectivity to remote hosts for network data collection.
Implements the interface expected by all collector modules.
"""

import os
import logging
from typing import Optional

import paramiko

logger = logging.getLogger(__name__)


class SSHClientError(Exception):
    """Exception raised for SSH client errors."""
    pass


class SSHClient:
    """
    SSH client for executing commands on remote hosts.

    Implements the interface required by collector modules:
    - execute(cmd: str) -> str

    Supports both key-based and password authentication.
    """

    def __init__(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        auth_type: str = "key",
        key_file: Optional[str] = None,
        password: Optional[str] = None,
        timeout: int = 10
    ):
        """
        Initialize SSH client.

        Args:
            hostname: Remote host IP or hostname
            port: SSH port (default: 22)
            username: SSH username (default: root)
            auth_type: Authentication type - "key" or "password"
            key_file: Path to private key file (for key auth)
            password: Password (for password auth)
            timeout: Connection timeout in seconds
        """
        self.hostname = hostname
        self.port = port
        self.username = username
        self.auth_type = auth_type
        self.key_file = key_file
        self.password = password
        self.timeout = timeout

        self._client: Optional[paramiko.SSHClient] = None
        self._connected = False

    def connect(self) -> None:
        """
        Establish SSH connection to the remote host.

        Raises:
            SSHClientError: If connection fails
        """
        if self._connected:
            return

        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            connect_kwargs = {
                "hostname": self.hostname,
                "port": self.port,
                "username": self.username,
                "timeout": self.timeout,
                "allow_agent": False,
                "look_for_keys": False,
            }

            if self.auth_type == "key":
                key_path = self._resolve_key_path()
                if key_path:
                    connect_kwargs["key_filename"] = key_path
                else:
                    # Fall back to allowing agent/keys lookup
                    connect_kwargs["allow_agent"] = True
                    connect_kwargs["look_for_keys"] = True
            elif self.auth_type == "password":
                if not self.password:
                    raise SSHClientError("Password authentication requires a password")
                connect_kwargs["password"] = self.password
            else:
                raise SSHClientError(f"Unknown auth_type: {self.auth_type}")

            logger.debug(f"Connecting to {self.hostname}:{self.port} as {self.username}")
            self._client.connect(**connect_kwargs)
            self._connected = True
            logger.info(f"Connected to {self.hostname}")

        except paramiko.AuthenticationException as e:
            raise SSHClientError(f"Authentication failed for {self.hostname}: {e}")
        except paramiko.SSHException as e:
            raise SSHClientError(f"SSH error connecting to {self.hostname}: {e}")
        except OSError as e:
            raise SSHClientError(f"Network error connecting to {self.hostname}: {e}")

    def _resolve_key_path(self) -> Optional[str]:
        """Resolve the SSH key file path, expanding ~ and checking existence."""
        if not self.key_file:
            return None

        path = os.path.expanduser(self.key_file)
        if os.path.isfile(path):
            return path

        logger.warning(f"Key file not found: {path}")
        return None

    def execute(self, cmd: str) -> str:
        """
        Execute a command on the remote host.

        Args:
            cmd: Command to execute

        Returns:
            Command output (stdout)

        Raises:
            SSHClientError: If not connected or command execution fails
        """
        if not self._connected or not self._client:
            self.connect()

        try:
            logger.debug(f"Executing on {self.hostname}: {cmd}")
            stdin, stdout, stderr = self._client.exec_command(cmd, timeout=self.timeout)

            output = stdout.read().decode("utf-8", errors="replace")
            error = stderr.read().decode("utf-8", errors="replace")

            exit_status = stdout.channel.recv_exit_status()

            if exit_status != 0 and error:
                logger.debug(f"Command returned {exit_status}: {error.strip()}")

            return output

        except paramiko.SSHException as e:
            raise SSHClientError(f"Failed to execute command on {self.hostname}: {e}")

    def close(self) -> None:
        """Close the SSH connection."""
        if self._client:
            self._client.close()
            self._client = None
        self._connected = False
        logger.debug(f"Disconnected from {self.hostname}")

    def __enter__(self) -> "SSHClient":
        """Context manager entry - connect to host."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - close connection."""
        self.close()

    def __repr__(self) -> str:
        return f"SSHClient({self.username}@{self.hostname}:{self.port})"
