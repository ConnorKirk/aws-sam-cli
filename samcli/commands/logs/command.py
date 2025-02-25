"""
CLI command for "logs" command
"""

import logging

import click

from samcli.cli.cli_config_file import ConfigProvider, configuration_option
from samcli.cli.main import aws_creds_options, pass_context, print_cmdline_args
from samcli.cli.main import common_options as cli_framework_options
from samcli.commands._utils.command_exception_handler import command_exception_handler
from samcli.commands._utils.options import common_observability_options, generate_next_command_recommendation
from samcli.commands.logs.core.command import LogsCommand
from samcli.commands.logs.validation_and_exception_handlers import (
    SAM_LOGS_ADDITIONAL_EXCEPTION_HANDLERS,
    stack_name_cw_log_group_validation,
)
from samcli.lib.telemetry.metric import track_command
from samcli.lib.utils.version_checker import check_newer_version

LOG = logging.getLogger(__name__)

SHORT_HELP = (
    "Fetch logs for your AWS SAM Application or AWS Cloudformation stack - Lambda Functions/CloudWatch Log groups"
)

HELP_TEXT = """
The sam logs commands fetches logs of Lambda Functions/CloudWatch log groups
with additional filtering by options.
"""

DESCRIPTION = """
  Fetch logs generated by Lambda functions or other Cloudwatch log groups with additional filtering.
"""


@click.command(
    "logs",
    short_help=SHORT_HELP,
    context_settings={
        "ignore_unknown_options": False,
        "allow_interspersed_args": True,
        "allow_extra_args": True,
        "max_content_width": 120,
    },
    cls=LogsCommand,
    help=HELP_TEXT,
    description=DESCRIPTION,
    requires_credentials=True,
)
@configuration_option(provider=ConfigProvider(section="parameters"))
@click.option(
    "--name",
    "-n",
    multiple=True,
    help="The name of the resource for which to fetch logs. If this resource is a part of an AWS CloudFormation stack, "
    "this can be the LogicalID of the resource in the CloudFormation/SAM template. "
    "Multiple names can be provided by repeating the parameter again. "
    "If resource is in a nested stack, name can be prepended by nested stack name to pull logs "
    "from that resource (NestedStackLogicalId/ResourceLogicalId). "
    "If it is not provided and no --cw-log-group have been given, it will scan "
    "given stack and find all supported resources, and start pulling log information from them.",
)
@click.option("--stack-name", default=None, help="Name of the AWS CloudFormation stack that the function is a part of.")
@click.option(
    "--filter",
    default=None,
    help="You can specify an expression to quickly find logs that match terms, phrases or values in "
    'your log events. This could be a simple keyword (e.g. "error") or a pattern '
    "supported by AWS CloudWatch Logs. See the AWS CloudWatch Logs documentation for the syntax "
    "https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/FilterAndPatternSyntax.html",
)
@click.option(
    "--include-traces",
    "-i",
    is_flag=True,
    help="Include the XRay traces in the log output.",
)
@click.option(
    "--cw-log-group",
    multiple=True,
    help="Additional CloudWatch Log group names that are not auto-discovered based upon --name parameter. "
    "When provided, it will only tail the given CloudWatch Log groups. If you want to tail log groups related "
    "to resources, please also provide their names as well",
)
@common_observability_options
@cli_framework_options
@aws_creds_options
@pass_context
@track_command
@check_newer_version
@print_cmdline_args
@command_exception_handler(SAM_LOGS_ADDITIONAL_EXCEPTION_HANDLERS)
@stack_name_cw_log_group_validation
def cli(
    ctx,
    name,
    stack_name,
    filter,
    tail,
    include_traces,
    start_time,
    end_time,
    output,
    cw_log_group,
    config_file,
    config_env,
):  # pylint: disable=redefined-builtin
    """
    `sam logs` command entry point
    """
    # All logic must be implemented in the ``do_cli`` method. This helps with easy unit testing

    do_cli(
        name,
        stack_name,
        filter,
        tail,
        include_traces,
        start_time,
        end_time,
        cw_log_group,
        output,
        ctx.region,
        ctx.profile,
    )  # pragma: no cover


def do_cli(
    names,
    stack_name,
    filter_pattern,
    tailing,
    include_tracing,
    start_time,
    end_time,
    cw_log_groups,
    output,
    region,
    profile,
):
    """
    Implementation of the ``cli`` method
    """

    from datetime import datetime

    from samcli.commands.logs.logs_context import ResourcePhysicalIdResolver, parse_time
    from samcli.commands.logs.puller_factory import generate_puller
    from samcli.lib.observability.util import OutputOption
    from samcli.lib.utils.boto_utils import get_boto_client_provider_with_config, get_boto_resource_provider_with_config

    if names and len(names) <= 1:
        click.echo(
            "You can now use 'sam logs' without --name parameter, "
            "which will pull the logs from all supported resources in your stack."
        )

    sanitized_start_time = parse_time(start_time, "start-time")
    sanitized_end_time = parse_time(end_time, "end-time") or datetime.utcnow()

    boto_client_provider = get_boto_client_provider_with_config(region=region, profile=profile)
    boto_resource_provider = get_boto_resource_provider_with_config(region=region, profile=profile)
    resource_logical_id_resolver = ResourcePhysicalIdResolver(
        boto_resource_provider, boto_client_provider, stack_name, names
    )

    # only fetch all resources when no CloudWatch log group defined
    fetch_all_when_no_resource_name_given = not cw_log_groups
    puller = generate_puller(
        boto_client_provider,
        resource_logical_id_resolver.get_resource_information(fetch_all_when_no_resource_name_given),
        filter_pattern,
        cw_log_groups,
        OutputOption(output) if output else OutputOption.text,
        include_tracing,
    )

    if tailing:
        puller.tail(sanitized_start_time, filter_pattern)
    else:
        puller.load_time_period(sanitized_start_time, sanitized_end_time, filter_pattern)

    if tailing:
        command_suggestions = generate_next_command_recommendation(
            [
                (
                    "Tail Logs from All Support Resources and X-Ray",
                    f"sam logs --stack-name {stack_name} --tail --include-traces",
                ),
                ("Tail X-Ray Information", "sam traces --tail"),
            ]
        )
        click.secho(command_suggestions, fg="yellow")
