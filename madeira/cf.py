import madeira
import boto3
import botocore.exceptions
import time


class Cf(object):

    def __init__(self, logger=None, profile_name=None, region=None):
        self._session = boto3.session.Session(
            profile_name=profile_name, region_name=region
        )
        self.cf_client = self._session.client('cloudformation')
        self._logger = logger if logger else madeira.get_logger()
        self._max_status_checks = 20
        self._status_check_interval = 20

    def _wait_for_status(self, stack_name, desired_status, max_status_checks=None, status_check_interval=None):
        max_status_checks = max_status_checks if max_status_checks else self._max_status_checks
        status_check_interval = status_check_interval if status_check_interval else self._status_check_interval

        # wait for stack "final" state
        status_check = 0

        while status_check < max_status_checks:
            status_check += 1

            try:
                stack = self.cf_client.describe_stacks(StackName=stack_name)['Stacks'][0]
            except botocore.exceptions.ClientError as e:
                stack_missing_msg = f'Stack with id {stack_name} does not exist'
                if stack_missing_msg in str(e) and desired_status == 'DELETE_COMPLETE':
                    return True
                else:
                    raise

            if stack['StackStatus'].startswith('UPDATE_ROLLBACK_') or stack['StackStatus'].startswith('ROLLBACK_'):
                self._logger.error('CF stack %s has known bad status: %s', stack['StackName'], stack['StackStatus'])
                self._logger.error('Please fix the issue, delete the CF stack, and try again.')
                return False

            elif stack['StackStatus'] == 'DELETE_FAILED':
                self._logger.critical('Stack %s deletion failed. Please check the AWS console.', stack['StackName'])
                return False

            elif stack['StackStatus'] == desired_status:
                self._logger.info('Stack %s deployment complete', stack['StackName'])
                return True

            self._logger.debug('CF stack status is: %s - waiting...', stack['StackStatus'])

            if status_check >= max_status_checks:
                raise RuntimeError('Timed out waiting for CF template to deploy')

            time.sleep(status_check_interval)

    def create_stack(self, stack_name, template_body, params=None, tags=None, termination_protection=True,
                     max_status_checks=None, status_check_interval=None):
        try:
            if self.cf_client.describe_stacks(StackName=stack_name).get('Stacks'):
                self._logger.warning('Stack with name: %s already exists - skipping', stack_name)
                return False

        # TODO: clean this up once the CF client object's "exceptions" property has a clean
        # exception to process consistent with other AWS service-specific exceptions
        except botocore.exceptions.ClientError as e:
            if f'Stack with id {stack_name} does not exist' in str(e):
                self._logger.debug('Stack %s does not exist', stack_name)
            else:
                raise

        if not params:
            params = []

        if not tags:
            tags = []

        self._logger.info('Requesting creation of stack: %s', stack_name)
        response = self.cf_client.create_stack(
            StackName=stack_name,
            Capabilities=['CAPABILITY_NAMED_IAM'],
            Parameters=params,
            TemplateBody=template_body,
            Tags=tags,
            EnableTerminationProtection=termination_protection
        )

        stack_arn = response['StackId']
        self._logger.debug('New stack ARN: %s', stack_arn)

        result = self._wait_for_status(stack_name, 'CREATE_COMPLETE', max_status_checks=max_status_checks,
                                       status_check_interval=status_check_interval)

        return stack_arn if result else False

    def create_or_update_stack(self, stack_name, template_body, params=None, tags=None, termination_protection=True,
                               max_status_checks=None, status_check_interval=None):
        try:
            # update the existing stack if it exists
            if self.cf_client.describe_stacks(StackName=stack_name):
                return self.update_stack(stack_name, template_body, params=params, tags=tags,
                                         max_status_checks=max_status_checks,
                                         status_check_interval=status_check_interval)

        # TODO: clean this up once the CF client object's "exceptions" property has a clean
        # exception to process consistent with other AWS service-specific exceptions
        except botocore.exceptions.ClientError as e:

            # create the stack that does not exist
            if f'Stack with id {stack_name} does not exist' in str(e):
                return self.create_stack(stack_name, template_body, params=params, tags=tags,
                                         termination_protection=termination_protection,
                                         max_status_checks=max_status_checks,
                                         status_check_interval=status_check_interval)
            else:
                raise

    def create_bucket_using_cf(
        self,
        bucket_name,
        cf_stack_name,
        cf_template_file,
        logging_bucket_name,
        vpc_id=None,
    ):
        with open(cf_template_file, "r") as f:
            template_body = f.read()

        params = [
            {"ParameterKey": "BucketName", "ParameterValue": bucket_name},
            {
                "ParameterKey": "LoggingBucketName",
                "ParameterValue": logging_bucket_name,
            },
        ]

        if vpc_id:
            params.append({"ParameterKey": "VpcId", "ParameterValue": vpc_id})

        self.create_stack(cf_stack_name, template_body, params)

    def create_or_update_bucket_using_cf(
        self,
        bucket_name,
        cf_stack_name,
        cf_template_file,
        logging_bucket_name,
        vpc_id=None,
    ):
        with open(cf_template_file, "r") as f:
            template_body = f.read()

        params = [
            {"ParameterKey": "BucketName", "ParameterValue": bucket_name},
            {
                "ParameterKey": "LoggingBucketName",
                "ParameterValue": logging_bucket_name,
            },
        ]

        if vpc_id:
            params.append({"ParameterKey": "VpcId", "ParameterValue": vpc_id})

        self.create_or_update_stack(cf_stack_name, template_body, params)

    def create_bucket_using_cf_custom_params(self, cf_stack_name, cf_template_file, parameters):
        with open(cf_template_file, "r") as f:
            template_body = f.read()

        self.create_stack(cf_stack_name, template_body, params=parameters)

    def create_or_update_bucket_using_cf_custom_params(self, cf_stack_name, cf_template_file, parameters):
        with open(cf_template_file, "r") as f:
            template_body = f.read()

        self.create_or_update_stack(
            cf_stack_name, template_body, params=parameters
        )

    def delete_stack(self, stack_name, max_status_checks=None, disable_termination_protection=False,
                     status_check_interval=None):
        max_status_checks = max_status_checks if max_status_checks else self._max_status_checks
        status_check_interval = status_check_interval if status_check_interval else self._status_check_interval
        stack = self.get_stack(stack_name)

        if not stack:
            self._logger.info('Stack: %s does not exist', stack_name)
            return

        if stack['StackStatus'] in ['DELETE_COMPLETE', 'DELETE_IN_PROGRESS']:
            self._logger.warning('Skipping stack: %s due to status: %s', stack['StackName'], stack['StackStatus'])
            return

        if disable_termination_protection:
            self._logger.info('Disabling termination protection for %s', stack_name)
            self.cf_client.update_termination_protection(EnableTerminationProtection=False, StackName=stack_name)

        self._logger.info('Requesting deletion of stack: %s', stack_name)
        self.cf_client.delete_stack(StackName=stack_name)

        return self._wait_for_status(stack_name, 'DELETE_COMPLETE', max_status_checks=max_status_checks,
                                     status_check_interval=status_check_interval)

    def get_stack(self, stack_name):
        try:
            return self.cf_client.describe_stacks(StackName=stack_name)['Stacks'][0]
        except botocore.exceptions.ClientError as e:
            if 'does not exist' in str(e):
                return
            else:
                raise

    def get_stack_outputs(self, stack_name):
        stack = self.get_stack(stack_name)
        return {output['OutputKey']: output['OutputValue'] for output in stack['Outputs']}

    def get_stacks(self):
        return self.cf_client.describe_stacks().get('Stacks')

    def update_stack(self, stack_name, template_body, params=None, tags=None,
                     max_status_checks=None, status_check_interval=None):
        try:
            existing_stack = self.cf_client.describe_stacks(StackName=stack_name).get('Stacks')[0]
            if (existing_stack['StackStatus'].startswith('DELETE') or
                    existing_stack['StackStatus'].startswith('ROLLBACK')):
                self._logger.error('Stack: %s has status: %s which is impossible to update', stack_name,
                                   existing_stack['StackStatus'])
                return False

        except botocore.exceptions.ClientError as e:
            if f'Stack with id {stack_name} does not exist' in str(e):
                self._logger.debug('Stack %s does not exist', stack_name)
                return False

        if not params:
            params = []

        if not tags:
            tags = []

        self._logger.info('Requesting update of stack: %s', stack_name)

        try:
            self.cf_client.update_stack(
                StackName=stack_name,
                Capabilities=['CAPABILITY_NAMED_IAM'],
                Parameters=params,
                TemplateBody=template_body,
                Tags=tags
            )
        except botocore.exceptions.ClientError as e:
            if 'No updates are to be performed' in str(e):
                self._logger.info('No updates are required for this stack at this time')
                return True
            else:
                raise

        # TODO: should we bother to return the stack ARN as in create_stack?
        return self._wait_for_status(stack_name, 'UPDATE_COMPLETE', max_status_checks=max_status_checks,
                                     status_check_interval=status_check_interval)
