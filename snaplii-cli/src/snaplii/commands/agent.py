import click

from snaplii.commands.agent_connection import agent_connect_cmd, agent_connection_cmd, agent_disconnect_cmd
from snaplii.commands.agent_orders import (
    agent_balance_cmd,
    agent_buy_cmd,
    agent_catalog_cmd,
    agent_order_cmd,
    agent_top_up_cancel_cmd,
    agent_top_up_cmd,
    agent_top_up_status_cmd,
)


@click.group("agent")
def agent_group():
    """Phone connection: connect by a texted link, top up Snaplii Cash, buy under the agent's daily limit.

    Side by side with the API-key session of 'snaplii init': its own token, its own commands.
    """


for command in (
    agent_connect_cmd,
    agent_connection_cmd,
    agent_disconnect_cmd,
    agent_balance_cmd,
    agent_catalog_cmd,
    agent_buy_cmd,
    agent_order_cmd,
    agent_top_up_cmd,
    agent_top_up_status_cmd,
    agent_top_up_cancel_cmd,
):
    agent_group.add_command(command)
