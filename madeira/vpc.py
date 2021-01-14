import madeira
import botocore.exceptions
import boto3
import time


class Vpc(object):
    def __init__(self, logger=None, profile_name=None, region=None):
        self._session = boto3.session.Session(
            profile_name=profile_name, region_name=region
        )
        self.ec2_client = self._session.client("ec2")
        self.ec2_resource = self._session.resource("ec2")
        self._account_id = (
            self._session.client("sts").get_caller_identity().get("Account")
        )
        self._logger = logger if logger else madeira.get_logger()
        self._vpc_delete_wait = 30

    def _add_name_to_subnets(self, subnets):
        for subnet in subnets:
            for tag in subnet.get("Tags"):
                if tag["Key"] == "Name":
                    self._logger.debug(
                        "Adding subnet name: %s to subnet: %s",
                        tag["Value"],
                        subnet["SubnetId"]
                    )
                    subnet["Name"] = tag["Value"]

    def _nat_gateway_status_wait(self, nat_gateway_id, status):
        max_status_checks = 10
        status_check_interval = 20

        # wait for stack "final" state
        status_check = 0

        while status_check < max_status_checks:
            status_check += 1

            nat_gateway = self.ec2_client.describe_nat_gateways(
                Filters=[{"Name": "nat-gateway-id", "Values": [nat_gateway_id]}]
            ).get("NatGateways")[0]

            if nat_gateway["State"] == status:
                self._logger.debug(
                    "NAT gateway %s is now: %s", nat_gateway["NatGatewayId"], status
                )
                return

            self._logger.debug(
                "NAT gateway: %s status is: %s - waiting for status: %s",
                nat_gateway["NatGatewayId"],
                nat_gateway["State"],
                status,
            )

            if status_check >= max_status_checks:
                raise RuntimeError(
                    "Timed out waiting for NAT gateway: %s to be available",
                    nat_gateway["NatGatewayId"],
                )

            time.sleep(status_check_interval)

    def _peering_connection_wait(self, peering_id):
        max_status_checks = 20
        status_check_interval = 10
        # wait for stack "final" state
        status_check = 0
        while status_check < max_status_checks:
            status_check += 1

            try:
                self.ec2_client.describe_vpc_peering_connections(
                    VpcPeeringConnectionIds=[peering_id])
                self._logger.debug("VPC Peering Connection %s is now available", peering_id)
                break
            except botocore.exceptions.ClientError as e:
                if "InvalidVpcPeeringConnectionID.NotFound" not in str(e):
                    raise

            if status_check >= max_status_checks:
                raise RuntimeError(
                    "Timed out waiting for VPC peering connection: %s to be available",
                    peering_id,
                )

            self._logger.debug(
                "VPC peering connection: %s is not yet available - waiting...",
                peering_id
            )

            time.sleep(status_check_interval)

    def accept_vpc_peering_connection(self, peering_id, name):
        self._logger.info(
            "Accepting peering connection: %s in account: %s",
            peering_id,
            self._account_id,
        )
        self._peering_connection_wait(peering_id)
        self.ec2_client.create_tags(
            Resources=[peering_id], Tags=[{"Key": "Name", "Value": name}]
        )
        return self.ec2_client.accept_vpc_peering_connection(
            VpcPeeringConnectionId=peering_id
        )

    def create_and_attach_igw(self, vpc_id):
        if self.ec2_client.describe_internet_gateways(Filters=[
            {'Name': 'attachment.vpc-id', 'Values': [vpc_id]},
        ]).get('InternetGateways'):
            self._logger.info('There is already an internet gateway attached to VPC: %s', vpc_id)
            return

        self._logger.info("Creating internet gateway")
        igw_id = self.ec2_client.create_internet_gateway()["InternetGateway"][
            "InternetGatewayId"
        ]

        self._logger.info("Attaching internet gateway to VPC")
        self.ec2_client.attach_internet_gateway(InternetGatewayId=igw_id, VpcId=vpc_id)
        # add route for igw to VPC default route table
        self._logger.info("Adding route for internet gateway")
        self.ec2_client.create_route(
            DestinationCidrBlock="0.0.0.0/0",
            GatewayId=igw_id,
            RouteTableId=self.ec2_client.describe_route_tables(
                Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
            )["RouteTables"][0]["RouteTableId"],
        )

    def create_nat_gw_and_rt(self, vpc_id, name, public_subnet_id, private_subnet_id):
        if self.ec2_client.describe_nat_gateways(
                Filters=[
                    {"Name": "subnet-id", "Values": [public_subnet_id]},
                    {"Name": "tag:Name", "Values": [name]},
                    {"Name": "vpc-id", "Values": [vpc_id]},
                ]
        ).get("NatGateways"):
            self._logger.info(
                "NAT Gateway: %s using subnet: %s in VPC: %s already exists",
                name,
                public_subnet_id,
                vpc_id,
            )
            return

        self._logger.info("Allocating elastic IP for NAT gateway")
        eip_alloc_id = self.ec2_client.allocate_address(Domain="vpc").get(
            "AllocationId"
        )

        self._logger.info("Creating NAT gateway: %s", name)
        nat_gateway_id = (
            self.ec2_client.create_nat_gateway(
                AllocationId=eip_alloc_id, SubnetId=public_subnet_id
            )
            .get("NatGateway")
            .get("NatGatewayId")
        )
        self.ec2_client.create_tags(
            Resources=[nat_gateway_id], Tags=[{"Key": "Name", "Value": name}]
        )
        self._nat_gateway_status_wait(nat_gateway_id, "available")

        # create a new route table, set up routes
        self._logger.info("Creating route table")
        route_table_id = (
            self.ec2_client.create_route_table(VpcId=vpc_id)
            .get("RouteTable")
            .get("RouteTableId")
        )

        max_status_checks = 20
        status_check_interval = 10

        # wait for stack "final" state
        status_check = 0

        while status_check < max_status_checks:
            status_check += 1

            try:
                self.ec2_client.describe_route_tables(RouteTableIds=[route_table_id])
                self._logger.debug("Route Table %s is now available", route_table_id)
                break
            except botocore.exceptions.ClientError as e:
                if "InvalidRouteTableID.NotFound" not in str(e):
                    raise

            if status_check >= max_status_checks:
                raise RuntimeError(
                    "Timed out waiting for route_table: %s to be available",
                    route_table_id,
                )

            self._logger.debug(
                "Route table: %s is not yet available - waiting...",
                route_table_id
            )

            time.sleep(status_check_interval)

        self.ec2_client.create_tags(
            Resources=[route_table_id], Tags=[{"Key": "Name", "Value": name}]
        )

        self._logger.info("Adding internet-facing route")
        self.ec2_client.create_route(
            DestinationCidrBlock="0.0.0.0/0",
            GatewayId=nat_gateway_id,
            RouteTableId=route_table_id,
        )

        # associate this route table with the given "private" subnet
        self._logger.info(
            "Associating route table: %s with private subnet: %s",
            route_table_id,
            private_subnet_id,
        )
        self.ec2_client.associate_route_table(
            RouteTableId=route_table_id, SubnetId=private_subnet_id
        )

    def create_vpc_peer_route(self, cidr_block, route_table_id, vpc_peer_conn_id):
        try:
            self._logger.info(
                "Creating route to CIDR: %s in route table: %s via VPC peering connection: %s in account: %s",
                cidr_block,
                route_table_id,
                vpc_peer_conn_id,
                self._account_id,
            )
            return self.ec2_client.create_route(
                DestinationCidrBlock=cidr_block,
                RouteTableId=route_table_id,
                VpcPeeringConnectionId=vpc_peer_conn_id,
            )
        except botocore.exceptions.ClientError as e:
            if "RouteAlreadyExists" in str(e):
                self._logger.info("Route already exists")
                return
            else:
                raise

    def create_subnet(self, subnet_name, subnet_cidr, availability_zone, vpc_id):
        existing_subnets = self.ec2_client.describe_subnets(
            Filters=[
                {"Name": "availability-zone", "Values": [availability_zone]},
                {"Name": "cidr-block", "Values": [subnet_cidr]},
                {"Name": "vpc-id", "Values": [vpc_id]},
            ]).get("Subnets")
        if existing_subnets:
            self._logger.info(
                "Subnet in AZ: %s with CIDR: %s in VPC: %s already exists",
                availability_zone,
                subnet_cidr,
                vpc_id,
            )
            return existing_subnets[0]['SubnetId']

        self._logger.info(
            "Creating subnet: %s with CIDR: %s in AZ: %s",
            subnet_name,
            subnet_cidr,
            availability_zone,
        )
        subnet = self.ec2_client.create_subnet(
            AvailabilityZone=availability_zone, CidrBlock=subnet_cidr, VpcId=vpc_id
        )
        subnet_id = subnet["Subnet"]["SubnetId"]

        max_status_checks = 10
        status_check_interval = 5

        # wait for stack "final" state
        status_check = 0

        while status_check < max_status_checks:
            status_check += 1

            try:
                subnet = self.ec2_client.describe_subnets(SubnetIds=[subnet_id]).get(
                    "Subnets"
                )[0]
            except botocore.exceptions.ClientError as e:
                if "InvalidSubnetID.NotFound" not in str(e):
                    raise

            if subnet["State"] == "available":
                self._logger.debug("Subnet %s is now available", subnet["SubnetId"])
                break

            self._logger.debug(
                "Subnet: %s status is: %s - waiting...",
                subnet["SubnetId"],
                subnet["State"],
            )

            if status_check >= max_status_checks:
                raise RuntimeError(
                    "Timed out waiting for subnet: %s to be available",
                    subnet["SubnetId"],
                )

            time.sleep(status_check_interval)

        self._logger.debug(
            "Tagging subnet %s with name: %s", subnet["SubnetId"], subnet_name
        )
        self.ec2_client.create_tags(
            Resources=[subnet_id], Tags=[{"Key": "Name", "Value": subnet_name}]
        )
        return subnet_id

    def create_vpc(self, cidr_block, vpc_name):
        # if the VPC already exists, return the ID of the extant VPC (if there are many, we're in trouble)
        vpcs_with_cidr = self.ec2_client.describe_vpcs(
            Filters=[{"Name": "cidr", "Values": [cidr_block]}]
        ).get("Vpcs")
        if vpcs_with_cidr:
            self._logger.info("VPC with CIDR: %s already exists", cidr_block)
            return vpcs_with_cidr[0]["VpcId"]

        self._logger.info("Creating VPC with CIDR: %s", cidr_block)
        vpc = self.ec2_resource.create_vpc(CidrBlock=cidr_block)

        self._logger.debug("Waiting for VPC to be available")
        try:
            vpc.wait_until_available(
                Filters=[
                    {"Name": "state", "Values": ["available"]},
                    {"Name": "vpc-id", "Values": [vpc.id]},
                ]
            )
        except botocore.exceptions.WaiterError:
            self._logger.debug("VPC waiter not yet ready - trying again")
            time.sleep(5)
            vpc.wait_until_available(
                Filters=[
                    {"Name": "state", "Values": ["available"]},
                    {"Name": "vpc-id", "Values": [vpc.id]},
                ]
            )

        vpc.create_tags(Tags=[{"Key": "Name", "Value": vpc_name}])
        return vpc.id

    def create_vpc_peering_connection(self, vpc_id, peer_account_id, peer_vpc_id, name):
        vpc_peering_connection_id = self.get_vpc_peering_connection_id(
            vpc_id, peer_account_id, peer_vpc_id
        )
        if vpc_peering_connection_id:
            self._logger.info(
                "VPC peering from %s in account %s to %s in account %s already exists",
                vpc_id,
                self._account_id,
                peer_vpc_id,
                peer_account_id,
            )
            return vpc_peering_connection_id

        self._logger.info(
            "Requesting VPC peering from %s in account %s to %s in account %s",
            vpc_id,
            self._account_id,
            peer_vpc_id,
            peer_account_id,
        )
        # TODO: monitor the status and return peering connection ID once in "pending-acceptance" state
        vpc_peer_conn_id = (
            self.ec2_client.create_vpc_peering_connection(
                PeerOwnerId=peer_account_id, PeerVpcId=peer_vpc_id, VpcId=vpc_id
            )
            .get("VpcPeeringConnection")
            .get("VpcPeeringConnectionId")
        )

        # appears to be only way to name a VPC peering connection as of 2/13/2020
        self._peering_connection_wait(vpc_peer_conn_id)
        self.ec2_client.create_tags(
            Resources=[vpc_peer_conn_id], Tags=[{"Key": "Name", "Value": name}]
        )
        return vpc_peer_conn_id

    def delete_vpc(self, vpc_id):
        vpc = self.ec2_resource.Vpc(id=vpc_id)
        vpc.delete()

    def deep_delete_vpc(self, vpc_id):
        # we have to be very comprehensive since there is no way to do a "delete VPC and cascade" operation via
        # high-level API call.
        if not vpc_id:
            return

        self._logger.info("Deleting VPC child objects")
        vpc = self.ec2_resource.Vpc(id=vpc_id)
        if not vpc.id:
            self._logger.debug("VPC: %s does not exist", vpc_id)
            return

        # detach default dhcp_options if associated with the vpc
        dhcp_options_default = self.ec2_resource.DhcpOptions("default")
        if dhcp_options_default:
            dhcp_options_default.associate_with_vpc(VpcId=vpc.id)
        # delete all NAT gateways associated with the VPC
        for nat_gw in self.ec2_client.describe_nat_gateways(
            Filters=[
                {"Name": "vpc-id", "Values": [vpc_id]},
                {
                    "Name": "state",
                    "Values": ["pending", "failed", "available", "deleting"],
                },
            ]
        ).get("NatGateways"):
            self._logger.debug("Deleting NAT gateway: %s", nat_gw["NatGatewayId"])
            self.ec2_client.delete_nat_gateway(NatGatewayId=nat_gw["NatGatewayId"])
            self._nat_gateway_status_wait(nat_gw["NatGatewayId"], "deleted")

        # detach and delete all gateways associated with the vpc
        for gw in vpc.internet_gateways.all():
            self._logger.debug("Detaching and deleting Internet gateway: %s", gw.id)
            vpc.detach_internet_gateway(InternetGatewayId=gw.id)
            gw.delete()

        # delete all route table associations
        for rt in vpc.route_tables.all():
            for rta in rt.associations:
                # delete any associations other than that which denotes a route table is a "main" route table
                if not rta.main:
                    self._logger.debug("Deleting route table association: %s", rta.id)
                    rta.delete()

        # delete all route tables
        for rt in vpc.route_tables.all():
            # this has the side effect of never deleting the main route table (which gets deleted by virtue of deleting
            # the VPC / cannot be explicitly deleted by itself) since it always has the "main" association...
            if not rt.associations:
                self._logger.debug("Deleting route table: %s", rt.id)
                rt.delete()

        # delete our security groups
        for sg in vpc.security_groups.all():
            if sg.group_name != "default":
                self._logger.debug("Deleting security group: %s", sg.id)
                sg.delete()

        # delete any vpc peering connections
        for vpcpeer in self.ec2_client.describe_vpc_peering_connections(
            Filters=[{"Name": "requester-vpc-info.vpc-id", "Values": [vpc_id]}]
        )["VpcPeeringConnections"]:
            self._logger.debug(
                "Deleting VPC peering connection: %s", vpcpeer["VpcPeeringConnectionId"]
            )
            self.ec2_resource.VpcPeeringConnection(
                vpcpeer["VpcPeeringConnectionId"]
            ).delete()

        # delete non-default network acls
        for netacl in vpc.network_acls.all():
            if not netacl.is_default:
                self._logger.debug("Deleting network ACL: %s", netacl.id)
                netacl.delete()

        # delete network interfaces
        for subnet in vpc.subnets.all():
            for interface in subnet.network_interfaces.all():
                self._logger.debug("Deleting interface: %s", interface.id)
                interface.delete()
            self._logger.debug("Deleting subnet: %s", subnet.id)
            subnet.delete()

        # release elastic IPs
        for eip in self.ec2_client.describe_addresses().get("Addresses"):
            self._logger.debug("Releasing elastic IP: %s", eip["AllocationId"])
            self.ec2_client.release_address(AllocationId=eip["AllocationId"])

        # finally, delete the vpc
        self._logger.info("Deleting VPC: %s", vpc_id)
        vpc.delete()

    def delete_default_vpc(self):
        vpc_id = self.get_default_vpc_id()
        if not vpc_id:
            self._logger.info("There is no default VPC to delete")
            return

        self._logger.info(
            "Giving some time for deleted default VPC artifacts, if any, to be cleared"
        )
        time.sleep(self._vpc_delete_wait)
        return self.deep_delete_vpc(vpc_id)

    def delete_vpc_by_name(self, vpc_name):
        self.delete_vpc(self.get_vpc_id_by_name(vpc_name))

    def delete_vpc_peer_route(self, cidr_block, route_table_id):
        try:
            self._logger.info(
                "Deleting route to CIDR: %s in route table: %s in account: %s",
                cidr_block,
                route_table_id,
                self._account_id,
            )
            self.ec2_client.delete_route(
                DestinationCidrBlock=cidr_block, RouteTableId=route_table_id
            )
        except botocore.exceptions.ClientError as e:
            if "InvalidRoute.NotFound" in str(e):
                self._logger.info("  route does not exist")
                return
            raise

    def enable_dns_hostnames(self, vpc_id):
        self._logger.info("Enabling DNS hostnames support for VPC %s", vpc_id)
        self.ec2_client.modify_vpc_attribute(
            VpcId=vpc_id, EnableDnsHostnames={"Value": True}
        )

    def get_vpc_by_name(self, vpc_name):
        all_vpcs = self.ec2_client.describe_vpcs(
            Filters=[{"Name": "tag:Name", "Values": [vpc_name]}]
        )

        for vpc in all_vpcs["Vpcs"]:
            for tag in vpc["Tags"]:
                if tag["Key"] == "Name" and tag["Value"] == vpc_name:
                    return vpc
        return ""

    def get_vpc_peering_connection_id(self, vpc_id, peer_account_id, peer_vpc_id):
        vpc_peering_conns = self.ec2_client.describe_vpc_peering_connections(
            Filters=[
                {"Name": "accepter-vpc-info.vpc-id", "Values": [peer_vpc_id]},
                {"Name": "accepter-vpc-info.owner-id", "Values": [peer_account_id]},
                {"Name": "requester-vpc-info.vpc-id", "Values": [vpc_id]},
                {
                    "Name": "status-code",
                    "Values": ["pending-acceptance", "active", "provisioning"],
                },
            ]
        )
        if vpc_peering_conns.get("VpcPeeringConnections"):
            return vpc_peering_conns.get("VpcPeeringConnections")[0].get(
                "VpcPeeringConnectionId"
            )

    def get_default_vpc_id(self):
        all_vpcs = self.ec2_client.describe_vpcs()

        for vpc in all_vpcs["Vpcs"]:
            if vpc["IsDefault"]:
                return vpc["VpcId"]
        return ""

    def get_route_table_in_vpc(self, name, vpc_id):
        return (
            self.ec2_client.describe_route_tables(
                Filters=[
                    {"Name": "vpc-id", "Values": [vpc_id]},
                    {"Name": "tag:Name", "Values": [name]},
                ]
            )
            .get("RouteTables")[0]
            .get("RouteTableId")
        )

    def get_route_tables_in_vpc(self, vpc_id):
        return [
            route_table.get("RouteTableId")
            for route_table in self.ec2_client.describe_route_tables(
                Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
            ).get("RouteTables")
        ]

    def get_main_route_table_by_vpc_id(self, vpc_id):
        return (
            self.ec2_client.describe_route_tables(
                Filters=[
                    {"Name": "vpc-id", "Values": [vpc_id]},
                    {"Name": "association.main", "Values": ["true"]},
                ]
            )
            .get("RouteTables")[0]
            .get("RouteTableId")
        )

    def get_security_group_id(self, vpc_id, name="default"):
        vpc = self.ec2_resource.Vpc(id=vpc_id)
        for sg in vpc.security_groups.all():
            if sg.group_name == name:
                return sg.group_id

    def get_subnet_id_for_az(self, vpc_id, availability_zone):
        subnets = self.ec2_client.describe_subnets(
            Filters=[
                {"Name": "vpc-id", "Values": [vpc_id]},
                {"Name": "availability-zone", "Values": [availability_zone]},
            ]
        )
        try:
            return subnets["Subnets"][0]["SubnetId"]
        except IndexError:
            return False

    def get_subnets_for_az(self, vpc_id, availability_zone):
        subnets = self.ec2_client.describe_subnets(
            Filters=[
                {"Name": "vpc-id", "Values": [vpc_id]},
                {"Name": "availability-zone", "Values": [availability_zone]},
            ]
        ).get("Subnets")
        self._add_name_to_subnets(subnets)
        return subnets

    def get_subnet_ids_for_vpc(self, vpc_id):
        subnets = self.ec2_client.describe_subnets(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )
        return [subnet["SubnetId"] for subnet in subnets["Subnets"]]

    def get_subnets_for_vpc(self, vpc_id):
        subnets = self.ec2_client.describe_subnets(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        ).get("Subnets")
        self._add_name_to_subnets(subnets)
        return subnets
