"""Remote ACP adapter: stdio ACP agent → cloud Octop APIs (0045)."""

from octop.infra.acp_remote.agent import RemoteAcpAgent
from octop.infra.acp_remote.run import run_acp_remote

__all__ = ["RemoteAcpAgent", "run_acp_remote"]
