import aws_cdk as cdk
from aws_cdk import aws_ec2 as ec2
from constructs import Construct


class NetworkStack(cdk.Stack):
    def __init__(self, scope: Construct, id: str, **kw) -> None:
        super().__init__(scope, id, **kw)
        self.vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            # One NAT gateway (not one per AZ) is the main network cost saving for a
            # non-critical internal tool. Egress is needed for the OpenAI API.
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24),
                ec2.SubnetConfiguration(
                    name="app", subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS, cidr_mask=22
                ),
            ],
        )
        # Free gateway endpoint: S3 traffic (Athena results, data) skips the NAT gateway.
        self.vpc.add_gateway_endpoint("S3", service=ec2.GatewayVpcEndpointAwsService.S3)
        self.vpc.add_flow_log("FlowLog", traffic_type=ec2.FlowLogTrafficType.REJECT)
