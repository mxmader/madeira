from madeira import session, sts
from madeira_utils import loggers
import time


class Quicksight(object):

    DASHBOARD_ACTIONS = [
        "quicksight:DescribeDashboard",
        "quicksight:ListDashboardVersions",
        "quicksight:UpdateDashboardPermissions",
        "quicksight:QueryDashboard",
        "quicksight:UpdateDashboard",
        "quicksight:DeleteDashboard",
        "quicksight:DescribeDashboardPermissions",
        "quicksight:UpdateDashboardPublishedVersion",
    ]

    DASHBOARD_READER_ACTIONS = [
        "quicksight:DescribeDashboard",
        "quicksight:ListDashboardVersions",
        "quicksight:QueryDashboard",
    ]

    DATA_SET_ACTIONS = [
        "quicksight:DescribeDataSet",
        "quicksight:DescribeDataSetPermissions",
        "quicksight:PassDataSet",
        "quicksight:DescribeIngestion",
        "quicksight:ListIngestions",
        "quicksight:UpdateDataSet",
        "quicksight:DeleteDataSet",
        "quicksight:CreateIngestion",
        "quicksight:CancelIngestion",
        "quicksight:UpdateDataSetPermissions",
    ]

    DATA_SOURCE_ACTIONS = [
        "quicksight:DescribeDataSource",
        "quicksight:DescribeDataSourcePermissions",
        "quicksight:PassDataSource",
    ]

    TEMPLATE_ACTIONS = ["quicksight:DescribeTemplate"]

    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else loggers.get_logger()
        self._session = session.Session(logger=logger, profile_name=profile_name, region=region)
        self._sts = sts.Sts(logger=logger, profile_name=profile_name, region=region)

        self.quicksight_client = self._session.session.client("quicksight")
        self._max_status_checks = 20
        self._status_check_interval = 5

    def _wait_for_data_source_status(self, name, desired_status, max_status_checks=None, status_check_interval=None):
        max_status_checks = max_status_checks if max_status_checks else self._max_status_checks
        status_check_interval = status_check_interval if status_check_interval else self._status_check_interval

        # wait for stack "final" state
        status_check = 0

        while status_check < max_status_checks:
            status_check += 1
            data_source = self.quicksight_client.describe_data_source(
                AwsAccountId=self._sts.account_id, DataSourceId=name).get("DataSource")

            if data_source["Status"].endswith("FAILED"):
                self._logger.error(
                    "Data source: %s has known bad status: %s", name, data_source["Status"])
                self._logger.error("Error message: %s", data_source["ErrorInfo"]["Message"])
                self._logger.error("Please fix the issue and try again.")
                return False

            elif data_source["Status"] == desired_status:
                self._logger.info("Data source: %s deployment complete", name)
                return True

            self._logger.debug("Data source: %s status is: %s", name, data_source["Status"])
            self._logger.debug("Waiting...")

            if status_check >= max_status_checks:
                raise RuntimeError("Timed out waiting for QuickSight Data Source to deploy")

            time.sleep(status_check_interval)

    def copy_or_update_analysis_template(
            self, name, source_template_id, permissions=None, source_account_id=None, max_status_checks=None,
            status_check_interval=None):
        source_account_id = source_account_id if source_account_id else self._sts.account_id
        source_template_arn = (f"arn:aws:quicksight:{self._session.region}:{source_account_id}:"
                               f"template/{source_template_id}")
        self._logger.debug("Using source template ARN: %s", source_template_arn)
        args = dict(
            AwsAccountId=self._sts.account_id,
            TemplateId=name,
            Name=name,
            SourceEntity={"SourceTemplate": {"Arn": source_template_arn}},
        )
        try:
            self.quicksight_client.describe_template(AwsAccountId=self._sts.account_id, TemplateId=name)
            # TODO: use update_template instead / get it working.
            self._logger.info(
                "Deleting quicksight template: %s from account: %s", name, self._sts.account_id)
            self.quicksight_client.delete_template(AwsAccountId=self._sts.account_id, TemplateId=name)
            # self._logger.info('Updating quicksight template: %s from template: %s from account: %s',
            #                   name, source_template_id, source_account_id)
            # result = self._quicksight_client.update_template(**args)
            # if permissions:
            #     self._logger.info('Updating permissions on quicksight template: %s', name)
            #     self._quicksight_client.update_template_permissions(AwsAccountId=self._sts.account_id, TemplateId=name,
            #                                                         GrantPermissions=permissions)
            # return result
        except self.quicksight_client.exceptions.ResourceNotFoundException:
            pass
        self._logger.info("Creating quicksight template: %s in account: %s from template: %s from account: %s",
                          name, self._sts.account_id, source_template_id, source_account_id)
        if permissions:
            args["Permissions"] = permissions

        self.quicksight_client.create_template(**args)

        max_status_checks = (max_status_checks if max_status_checks else self._max_status_checks)
        status_check_interval = (status_check_interval if status_check_interval else self._status_check_interval)

        # wait for stack "final" state
        status_check = 0

        template_version = (self.quicksight_client.describe_template(
            AwsAccountId=self._sts.account_id, TemplateId=name).get("Template").get("Version"))

        while status_check < max_status_checks:
            status_check += 1

            if template_version["Status"].endswith("FAILED"):
                errors = ",".join([f"{error['Type']} - {error['Message']}"
                                   for error in template_version["Errors"]])
                self._logger.error("Template: %s has known bad status: %s", name, template_version["Status"])
                self._logger.error("Error message(s): %s", errors)
                self._logger.error("Please fix the issue and try again.")
                return False

            elif template_version["Status"] == "CREATION_SUCCESSFUL":
                self._logger.info("Template: %s deployment complete", name)
                return True

            self._logger.debug("Data source: %s status is: %s", name, template_version["Status"])
            self._logger.debug("Waiting...")

            if status_check >= max_status_checks:
                raise RuntimeError("Timed out waiting for QuickSight template to deploy")

            time.sleep(status_check_interval)
            template_version = self.quicksight_client.describe_template(
                    AwsAccountId=self._sts.account_id, TemplateId=name).get("Template").get("Version")

        version_number = template_version["VersionNumber"]
        self.quicksight_client.update_template_published_version(
            AwsAccountId=self._sts.account_id, TemplateId=name, VersionNumber=version_number
        )

    def create_or_update_analysis_template(
            self, name, source_analysis_id, data_set_references, permissions=None, source_account_id=None):

        source_account_id = source_account_id if source_account_id else self._sts.account_id
        source_analysis_arn = (f"arn:aws:quicksight:{self._session.region}:{source_account_id}:"
                               f"analysis/{source_analysis_id}")
        args = dict(
            AwsAccountId=self._sts.account_id, TemplateId=name, Name=name,
            SourceEntity={
                "SourceAnalysis": {
                    "Arn": source_analysis_arn,
                    "DataSetReferences": data_set_references,
                }
            }
        )

        try:
            self.quicksight_client.describe_template(AwsAccountId=self._sts.account_id, TemplateId=name)
            self._logger.info("Updating quicksight template: %s from analysis: %s", name, source_analysis_id)
            self.quicksight_client.update_template(**args)
            if permissions:
                self._logger.info("Updating permissions on quicksight template: %s", name)
                self.quicksight_client.update_template_permissions(
                    AwsAccountId=self._sts.account_id, TemplateId=name, GrantPermissions=permissions)
        except self.quicksight_client.exceptions.ResourceNotFoundException:
            self._logger.info("Creating quicksight template: %s from analysis: %s", name, source_analysis_id)
            if permissions:
                args["Permissions"] = permissions
            return self.quicksight_client.create_template(**args)

    def create_or_update_dashboard_from_template(
            self, name, dashboard_id, source_template_id, data_set_references, permissions=None, publish_options=None,
            source_account_id=None, max_status_checks=None, status_check_interval=None):

        source_account_id = source_account_id if source_account_id else self._sts.account_id
        source_template_arn = (f"arn:aws:quicksight:{self._session.region}:{source_account_id}:"
                               f"template/{source_template_id}")

        if not publish_options:
            publish_options = {
                "AdHocFilteringOption": {"AvailabilityStatus": "ENABLED"},
                "ExportToCSVOption": {"AvailabilityStatus": "DISABLED"},
                "SheetControlsOption": {"VisibilityState": "EXPANDED"},
            }

        args = dict(
            AwsAccountId=self._sts.account_id,
            DashboardId=dashboard_id,
            Name=name,
            SourceEntity={
                "SourceTemplate": {
                    "DataSetReferences": data_set_references,
                    "Arn": source_template_arn,
                }
            },
            DashboardPublishOptions=publish_options,
        )

        try:
            dashboard = self.quicksight_client.describe_dashboard(
                AwsAccountId=self._sts.account_id, DashboardId=dashboard_id)
            self._logger.info("Updating quicksight dashboard: %s from template: %s", name, source_template_id)
            self.quicksight_client.update_dashboard(**args)
            self._logger.info("Publishing version: %s of dashboard: %s",
                              dashboard["Dashboard"]["Version"]["VersionNumber"], name)
            self.quicksight_client.update_dashboard_published_version(
                AwsAccountId=self._sts.account_id, DashboardId=dashboard_id,
                VersionNumber=dashboard["Dashboard"]["Version"]["VersionNumber"])
            if permissions:
                self._logger.info("Updating permissions for dashboard: %s", name)
                self.quicksight_client.update_dashboard_permissions(
                    AwsAccountId=self._sts.account_id,
                    DashboardId=dashboard_id,
                    GrantPermissions=permissions,
                )
        except self.quicksight_client.exceptions.ResourceNotFoundException:
            if permissions:
                args["Permissions"] = permissions
            self._logger.info("Creating dashboard: %s from template: %s", name, source_template_id)
            self.quicksight_client.create_dashboard(**args)

            max_status_checks = max_status_checks if max_status_checks else self._max_status_checks
            status_check_interval = status_check_interval if status_check_interval else self._status_check_interval

            # wait for stack "final" state
            status_check = 0

            dashboard_version = self.quicksight_client.describe_dashboard(
                    AwsAccountId=self._sts.account_id, DashboardId=dashboard_id).get("Dashboard").get("Version")

            while status_check < max_status_checks:
                status_check += 1

                if dashboard_version["Status"].endswith("FAILED"):
                    errors = ",".join([f"{error['Type']} - {error['Message']}"
                                       for error in dashboard_version["Errors"]])
                    self._logger.error("Dashboard: %s has known bad status: %s", name, dashboard_version["Status"])
                    self._logger.error("Error message(s): %s", errors)
                    self._logger.error("Please fix the issue and try again.")
                    return False

                elif dashboard_version["Status"] == "CREATION_SUCCESSFUL":
                    self._logger.info("Dashboard: %s deployment complete", name)
                    return True

                self._logger.debug("Dashboard: %s status is: %s", name, dashboard_version["Status"])
                self._logger.debug("Waiting...")

                if status_check >= max_status_checks:
                    raise RuntimeError("Timed out waiting for QuickSight dashboard to deploy")

                time.sleep(status_check_interval)
                dashboard_version = self.quicksight_client.describe_dashboard(
                        AwsAccountId=self._sts.account_id, DashboardId=name).get("Dashboard").get("Version")

            self._logger.info("Publishing version: %s of dashboard: %s", dashboard_version["VersionNumber"], name)
            self.quicksight_client.update_dashboard_published_version(
                AwsAccountId=self._sts.account_id,
                DashboardId=dashboard_id,
                VersionNumber=dashboard_version["VersionNumber"],
            )

    def create_or_update_athena_data_source(self, name, permissions=None):
        data_source = dict(
            AwsAccountId=self._sts.account_id, DataSourceId=name, Name=name, Type="ATHENA",
            DataSourceParameters={"AthenaParameters": {"WorkGroup": "primary"}})

        if permissions:
            data_source["Permissions"] = permissions

        try:
            self.quicksight_client.describe_data_source(AwsAccountId=self._sts.account_id, DataSourceId=name)
            self._logger.info("Updating granted permissions for data source: %s", name)
            self.quicksight_client.update_data_source_permissions(
                AwsAccountId=data_source["AwsAccountId"], DataSourceId=data_source["DataSourceId"],
                GrantPermissions=data_source["Permissions"])
            del data_source["Type"]
            del data_source["Permissions"]
            self._logger.info("Updating data source: %s", name)
            data_source_arn = self.quicksight_client.update_data_source(**data_source).get("Arn")
            self._wait_for_data_source_status(name, "UPDATE_SUCCESSFUL")

        except self.quicksight_client.exceptions.ResourceNotFoundException:
            self._logger.info("Creating data source: %s", name)
            data_source_arn = self.quicksight_client.create_data_source(**data_source).get("Arn")
            self._wait_for_data_source_status(name, "CREATION_SUCCESSFUL")

        return data_source_arn

    def create_or_update_athena_sql_data_set(
            self, name, sql, data_source_arn, columns, permissions=None, logical_table_map=None):

        data_set = {
            "AwsAccountId": self._sts.account_id,
            "DataSetId": name,
            "Name": name,
            "PhysicalTableMap": {
                name: {
                    "CustomSql": {
                        "DataSourceArn": data_source_arn,
                        "Name": name,
                        "SqlQuery": sql,
                        "Columns": columns,
                    }
                }
            },
            "ImportMode": "SPICE",
        }

        if permissions:
            data_set["Permissions"] = permissions

        if logical_table_map:
            data_set["LogicalTableMap"] = logical_table_map

        try:
            self.quicksight_client.describe_data_set(
                AwsAccountId=self._sts.account_id, DataSetId=name
            )
            self._logger.info("Updating granted permissions for data set: %s", name)
            if permissions:
                self.quicksight_client.update_data_set_permissions(
                    AwsAccountId=data_set["AwsAccountId"],
                    DataSetId=data_set["DataSetId"],
                    GrantPermissions=data_set["Permissions"],
                )
                del data_set["Permissions"]
            self._logger.info("Updating data set: %s", name)
            return self.quicksight_client.update_data_set(**data_set).get("Arn")
        except self.quicksight_client.exceptions.ResourceNotFoundException:
            self._logger.info("Creating data set: %s", name)
            return self.quicksight_client.create_data_set(**data_set)

    def create_or_update_group(self, name):
        try:
            self.quicksight_client.describe_group(AwsAccountId=self._sts.account_id, GroupName=name, Namespace="default")
            self._logger.warning("Updating quicksight groups is not currently supported; perhaps relevant when "
                                 "non-default namespaces are supported upstream")
        except self.quicksight_client.exceptions.ResourceNotFoundException:
            self._logger.info("Creating quicksight group: %s", name)
            return self.quicksight_client.create_group(
                AwsAccountId=self._sts.account_id, GroupName=name, Namespace="default")

    def delete_analysis_template(self, template_id):
        try:
            self.quicksight_client.describe_template(AwsAccountId=self._sts.account_id, TemplateId=template_id)
            self._logger.info("Deleting quicksight analysis template: %s", template_id)
            return self.quicksight_client.delete_template(AwsAccountId=self._sts.account_id, TemplateId=template_id)
        except self.quicksight_client.exceptions.ResourceNotFoundException:
            pass

    def delete_data_set(self, data_set_id):
        try:
            self.quicksight_client.describe_data_set(AwsAccountId=self._sts.account_id, DataSetId=data_set_id)
            self._logger.info("Deleting quicksight data set: %s", data_set_id)
            return self.quicksight_client.delete_data_set(AwsAccountId=self._sts.account_id, DataSetId=data_set_id)
        except self.quicksight_client.exceptions.ResourceNotFoundException:
            pass

    def delete_data_source(self, name):
        try:
            self.quicksight_client.describe_data_source(AwsAccountId=self._sts.account_id, DataSourceId=name)
            self._logger.info("Deleting data source: %s", name)
            return self.quicksight_client.delete_data_source(AwsAccountId=self._sts.account_id, DataSourceId=name)
        except self.quicksight_client.exceptions.ResourceNotFoundException:
            pass

    def delete_dashboard(self, name):
        try:
            self.quicksight_client.describe_dashboard(AwsAccountId=self._sts.account_id, DashboardId=name)
            self._logger.info("Deleting dashboard: %s", name)
            return self.quicksight_client.delete_dashboard(AwsAccountId=self._sts.account_id, DashboardId=name)
        except self.quicksight_client.exceptions.ResourceNotFoundException:
            pass

    def get_admin_principal_arns(self):
        # get the largest chunk of users possible according to AWS API limits
        max_results = 100
        quicksight_users = list()

        account_id = self._sts.account_id
        self._logger.debug("Reading first chunk of quicksight users")
        users_chunk = self.quicksight_client.list_users(
            AwsAccountId=self._sts.account_id, MaxResults=max_results, Namespace="default")
        quicksight_users.extend(users_chunk.get("UserList"))

        while users_chunk.get("NextToken"):
            self._logger.debug("Reading next chunk of quicksight users")
            users_chunk = self.quicksight_client.list_users(
                AwsAccountId=account_id, NextToken=users_chunk.get("NextToken"),
                MaxResults=max_results, Namespace="default")
            quicksight_users.extend(users_chunk.get("UserList"))

        return [user["Arn"] for user in quicksight_users
                if user["Role"] == "ADMIN" and user["Arn"] != "N/A"]

    def get_data_set_arn(self, name):
        try:
            return self.quicksight_client.describe_data_set(
                AwsAccountId=self._sts.account_id, DataSetId=name).get("DataSet").get("Arn")
        except self.quicksight_client.exceptions.ResourceNotFoundException:
            self._logger.warning("Could not find data set with ID: %s", name)
            return ""

    def get_group_arn(self, name):
        try:
            return self.quicksight_client.describe_group(
                AwsAccountId=self._sts.account_id, GroupName=name, Namespace="default").get("Group").get("Arn")
        except self.quicksight_client.exceptions.ResourceNotFoundException:
            self._logger.warning("Could not find group with name: %s", name)
            return ""

    def list_analysis_templates(self):
        # get the largest chunk of analysis templates possible according to AWS API limits
        max_results = 100
        analysis_templates = list()

        account_id = self._sts.account_id
        self._logger.debug("Reading first chunk of quicksight analysis templates")
        analysis_template_chunk = self.quicksight_client.list_templates(
            AwsAccountId=self._sts.account_id, MaxResults=max_results)
        analysis_templates.extend(analysis_template_chunk.get("TemplateSummaryList"))

        while analysis_template_chunk.get("NextToken"):
            self._logger.debug("Reading next chunk of quicksight analysis templates")
            analysis_template_chunk = self.quicksight_client.list_templates(
                AwsAccountId=account_id,
                NextToken=analysis_template_chunk.get("NextToken"), MaxResults=max_results)
            analysis_templates.extend(analysis_template_chunk.get("TemplateSummaryList"))

        return analysis_templates

    def list_dashboards(self):
        # get the largest chunk of dashboards possible according to AWS API limits
        max_results = 100
        dashboards = list()

        account_id = self._sts.account_id
        self._logger.debug("Reading first chunk of quicksight dashboards")
        dashboard_chunk = self.quicksight_client.list_dashboards(
            AwsAccountId=self._sts.account_id, MaxResults=max_results)
        dashboards.extend(dashboard_chunk.get("DashboardSummaryList"))

        while dashboard_chunk.get("NextToken"):
            self._logger.debug("Reading next chunk of quicksight dashboards")
            dashboard_chunk = self.quicksight_client.list_dashboards(
                AwsAccountId=account_id,
                NextToken=dashboard_chunk.get("NextToken"),
                MaxResults=max_results)
            dashboards.extend(dashboard_chunk.get("DashboardSummaryList"))

        return dashboards

    def list_data_sets(self):
        # get the largest chunk of data sets possible according to AWS API limits
        max_results = 100
        data_sets = list()

        account_id = self._sts.account_id
        self._logger.debug("Reading first chunk of quicksight data sets")
        data_set_chunk = self.quicksight_client.list_data_sets(
            AwsAccountId=self._sts.account_id, MaxResults=max_results)
        data_sets.extend(data_set_chunk.get("DataSetSummaries"))

        while data_set_chunk.get("NextToken"):
            self._logger.debug("Reading next chunk of quicksight data sets")
            data_set_chunk = self.quicksight_client.list_data_sets(
                AwsAccountId=account_id, NextToken=data_set_chunk.get("NextToken"), MaxResults=max_results)
            data_sets.extend(data_set_chunk.get("DataSetSummaries"))

        return data_sets

    def list_data_sources(self):
        # get the largest chunk of data sources possible according to AWS API limits
        max_results = 100
        data_sources = list()

        account_id = self._sts.account_id
        self._logger.debug("Reading first chunk of quicksight data sources")
        data_source_chunk = self.quicksight_client.list_data_sources(
            AwsAccountId=self._sts.account_id, MaxResults=max_results)
        data_sources.extend(data_source_chunk.get("DataSources"))

        while data_source_chunk.get("NextToken"):
            self._logger.debug("Reading next chunk of quicksight data sources")
            data_source_chunk = self.quicksight_client.list_data_sources(
                AwsAccountId=account_id, NextToken=data_source_chunk.get("NextToken"), MaxResults=max_results)
            data_sources.extend(data_source_chunk.get("DataSources"))

        return data_sources

    def set_template_permissions(self, template_id, permissions):
        return self.quicksight_client.update_template_permissions(
            AwsAccountId=self._sts.account_id, TemplateId=template_id, GrantPermissions=permissions)

    def update_template_permissions(self, name, permissions):
        self._logger.info("Updating permissions on quicksight template: %s", name)
        self.quicksight_client.update_template_permissions(
            AwsAccountId=self._sts.account_id, TemplateId=name, GrantPermissions=permissions)
