"""Property-based tests for rsync command construction.

Feature: file-storage-replication, Property 6: Rsync command construction

For any valid ``VolumeSyncConfig`` and source/destination path pair, the
constructed rsync command SHALL include the ``--archive``, ``--compress``,
and ``--delete`` flags, SHALL include ``-e "ssh -i {ssh_key_path} -p
{ssh_port}"`` for SSH authentication, and SHALL target
``{standby_ssh_host}:{dest_path}`` as the remote destination.

**Validates: Requirements 5.2, 5.3, 5.7, 5.8**

Uses Hypothesis to generate random valid configs (hosts, ports, key paths,
source/dest paths), calls ``build_rsync_command()`` and verifies the output
list contains the expected flags and values.  This is a pure function test
— no database needed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

from app.modules.ha.volume_sync_models import VolumeSyncConfig
from app.modules.ha.volume_sync_service import VolumeSyncService

# ---------------------------------------------------------------------------
# Hypothesis settings
# ---------------------------------------------------------------------------

PBT_SETTINGS = settings(
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Realistic SSH hosts: IPv4 addresses or hostnames
ssh_host_strategy = st.one_of(
    st.from_regex(
        r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}",
        fullmatch=True,
    ),
    st.text(
        alphabet=st.characters(
            whitelist_categories=("L", "N"),
            whitelist_characters=".-",
            min_codepoint=45,
            max_codepoint=122,
        ),
        min_size=1,
        max_size=50,
    ).filter(lambda s: s.strip() != "" and not s.startswith("-") and not s.startswith(".")),
)

# Valid SSH ports
ssh_port_strategy = st.integers(min_value=1, max_value=65535)

# SSH key paths — Unix-style absolute paths
ssh_key_path_strategy = st.one_of(
    st.just("/root/.ssh/id_rsa"),
    st.just("/home/user/.ssh/id_ed25519"),
    st.from_regex(r"/[a-z][a-z0-9_/]{1,40}/id_[a-z]{3,10}", fullmatch=True),
)

# Source and destination paths — Unix-style directory paths ending with /
path_strategy = st.from_regex(
    r"/[a-z][a-z0-9_/]{1,60}/",
    fullmatch=True,
)


def _make_config(
    host: str,
    port: int,
    key_path: str,
) -> VolumeSyncConfig:
    """Create a VolumeSyncConfig instance without a DB session.

    Uses the standard constructor — SQLAlchemy models can be instantiated
    without being added to a session.
    """
    now = datetime.now(timezone.utc)
    return VolumeSyncConfig(
        id=uuid.uuid4(),
        standby_ssh_host=host,
        ssh_port=port,
        ssh_key_path=key_path,
        remote_upload_path="/app/uploads/",
        remote_compliance_path="/app/compliance_files/",
        sync_interval_minutes=5,
        enabled=True,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Property 6: Rsync command construction
# Feature: file-storage-replication, Property 6: Rsync command construction
# **Validates: Requirements 5.2, 5.3, 5.7, 5.8**
# ---------------------------------------------------------------------------


class TestRsyncCommandConstructionProperty:
    """Property 6 — For any valid VolumeSyncConfig and source/destination
    path pair, the constructed rsync command SHALL include the --archive,
    --compress, and --delete flags, SHALL include
    -e "ssh -i {ssh_key_path} -p {ssh_port}" for SSH authentication,
    and SHALL target {standby_ssh_host}:{dest_path} as the remote
    destination."""

    @PBT_SETTINGS
    @given(
        host=ssh_host_strategy,
        port=ssh_port_strategy,
        key_path=ssh_key_path_strategy,
        source_path=path_strategy,
        dest_path=path_strategy,
    )
    def test_command_includes_required_flags(
        self, host, port, key_path, source_path, dest_path,
    ):
        """The rsync command SHALL include --archive, --compress, and
        --delete flags.

        **Validates: Requirements 5.2, 5.3, 5.7**
        """
        config = _make_config(host, port, key_path)
        svc = VolumeSyncService()

        cmd = svc.build_rsync_command(config, source_path, dest_path)

        # Must be a non-empty list starting with "rsync"
        assert isinstance(cmd, list), f"Expected list, got {type(cmd)}"
        assert len(cmd) > 0, "Command list is empty"
        assert cmd[0] == "rsync", f"First element should be 'rsync', got {cmd[0]!r}"

        # Required flags
        assert "--archive" in cmd, f"--archive flag missing from command: {cmd}"
        assert "--compress" in cmd, f"--compress flag missing from command: {cmd}"
        assert "--delete" in cmd, f"--delete flag missing from command: {cmd}"

    @PBT_SETTINGS
    @given(
        host=ssh_host_strategy,
        port=ssh_port_strategy,
        key_path=ssh_key_path_strategy,
        source_path=path_strategy,
        dest_path=path_strategy,
    )
    def test_command_includes_ssh_authentication(
        self, host, port, key_path, source_path, dest_path,
    ):
        """The rsync command SHALL include -e with SSH key and port for
        authentication.

        **Validates: Requirements 5.7, 5.8**
        """
        config = _make_config(host, port, key_path)
        svc = VolumeSyncService()

        cmd = svc.build_rsync_command(config, source_path, dest_path)

        # Find the -e flag and its argument
        assert "-e" in cmd, f"-e flag missing from command: {cmd}"
        e_index = cmd.index("-e")
        assert e_index + 1 < len(cmd), "-e flag has no argument"

        ssh_arg = cmd[e_index + 1]

        # SSH argument must reference the key path and port
        assert f"-i {key_path}" in ssh_arg, (
            f"SSH key path {key_path!r} not found in -e argument: {ssh_arg!r}"
        )
        assert f"-p {port}" in ssh_arg, (
            f"SSH port {port} not found in -e argument: {ssh_arg!r}"
        )

    @PBT_SETTINGS
    @given(
        host=ssh_host_strategy,
        port=ssh_port_strategy,
        key_path=ssh_key_path_strategy,
        source_path=path_strategy,
        dest_path=path_strategy,
    )
    def test_command_targets_remote_destination(
        self, host, port, key_path, source_path, dest_path,
    ):
        """The rsync command SHALL target {standby_ssh_host}:{dest_path}
        as the remote destination.

        **Validates: Requirements 5.2, 5.3, 5.8**
        """
        config = _make_config(host, port, key_path)
        svc = VolumeSyncService()

        cmd = svc.build_rsync_command(config, source_path, dest_path)

        # The last element should be the remote destination
        expected_dest = f"{host}:{dest_path}"
        assert expected_dest in cmd, (
            f"Remote destination {expected_dest!r} not found in command: {cmd}"
        )

        # Source path should also be present
        assert source_path in cmd, (
            f"Source path {source_path!r} not found in command: {cmd}"
        )

    @PBT_SETTINGS
    @given(
        host=ssh_host_strategy,
        port=ssh_port_strategy,
        key_path=ssh_key_path_strategy,
        source_path=path_strategy,
        dest_path=path_strategy,
    )
    def test_command_source_before_destination(
        self, host, port, key_path, source_path, dest_path,
    ):
        """The source path SHALL appear before the remote destination in
        the rsync command (rsync convention).

        **Validates: Requirements 5.2, 5.3**
        """
        config = _make_config(host, port, key_path)
        svc = VolumeSyncService()

        cmd = svc.build_rsync_command(config, source_path, dest_path)

        expected_dest = f"{host}:{dest_path}"
        source_index = cmd.index(source_path)
        dest_index = cmd.index(expected_dest)

        assert source_index < dest_index, (
            f"Source path (index {source_index}) should appear before "
            f"destination (index {dest_index}) in command: {cmd}"
        )
