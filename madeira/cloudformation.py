import re
import time

from madeira import session
from madeira_utils import loggers


class CloudFormation(object):

    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else loggers.get_logger()
        self._session = session.Session(logger=logger, profile_name=profile_name, region=region)

        self.cf_client = self._session.session.client('cloudformation')
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
            except self.cf_client.exceptions.ClientError as e:
                stack_missing_msg = f'Stack with id {stack_name} does not exist'
                if stack_missing_msg in str(e) and desired_status == 'DELETE_COMPLETE':
                    return True
                else:
                    raise

            if stack['StackStatus'].startswith('ROLLBACK_'):
                self._logger.error('%s: cloudformation stack cannot be deployed due to status: %s - delete and re-try',
                                   stack['StackName'], stack['StackStatus'])
                return False

            elif stack['StackStatus'] == 'DELETE_FAILED':
                self._logger.critical('%s: cloudformation stack deletion failed - please investigate',
                                      stack['StackName'])
                return False

            elif stack['StackStatus'] == desired_status:
                self._logger.info('%s: cloudformation stack deployment complete', stack['StackName'])
                return True

            self._logger.info('%s: cloudformation stack status: %s; waiting', stack['StackName'], stack['StackStatus'])

            if status_check >= max_status_checks:
                raise RuntimeError('%s: deployment timed out')

            time.sleep(status_check_interval)

    def create_stack(self, stack_name, template_body, params=None, tags=None, termination_protection=True,
                     max_status_checks=None, status_check_interval=None):
        try:
            if self.cf_client.describe_stacks(StackName=stack_name).get('Stacks'):
                self._logger.warning('Stack with name: %s already exists - skipping', stack_name)
                return False

        except self.cf_client.exceptions.ClientError as e:
            if f'Stack with id {stack_name} does not exist' in str(e):
                self._logger.debug('%s: cloudformation stack does not exist', stack_name)
            else:
                raise

        if not params:
            params = []

        if not tags:
            tags = []

        self._logger.info('%s: requesting creation of stack', stack_name)
        response = self.cf_client.create_stack(
            StackName=stack_name,
            Capabilities=['CAPABILITY_NAMED_IAM'],
            Parameters=params,
            TemplateBody=template_body,
            Tags=tags,
            EnableTerminationProtection=termination_protection
        )

        stack_arn = response['StackId']
        self._logger.debug('%s: cloudformation stack ARN: %s', stack_name, stack_arn)

        result = self._wait_for_status(stack_name, 'CREATE_COMPLETE', max_status_checks=max_status_checks,
                                       status_check_interval=status_check_interval)

        return stack_arn if result else False

    def create_or_update_stack(self, stack_name, template_body, params=None, tags=None, termination_protection=True,
                               max_status_checks=None, status_check_interval=None):
        stack = self.get_stack(stack_name)

        if stack:
            if stack['StackStatus'] == 'ROLLBACK_COMPLETE':
                self._logger.info('%s: cleaning up cloudformation stack from failed initial deployment', stack_name)
                self.delete_stack(stack_name, disable_termination_protection=termination_protection)
            else:
                # update the existing stack
                self._logger.info('%s: cloudformation stack already exists - may need update', stack_name)
                return self.update_stack(stack_name, template_body, params=params, tags=tags,
                                         max_status_checks=max_status_checks,
                                         status_check_interval=status_check_interval)

        # create the stack that does not exist (or was cleaned up)
        return self.create_stack(stack_name, template_body, params=params, tags=tags,
                                 termination_protection=termination_protection,
                                 max_status_checks=max_status_checks,
                                 status_check_interval=status_check_interval)

    def create_bucket_using_cf(self, bucket_name, cf_stack_name, cf_template_file, logging_bucket_name, vpc_id=None):
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
            self, bucket_name, cf_stack_name, cf_template_file, logging_bucket_name, vpc_id=None):
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
            self._logger.info('%s: cloudformation stack does not exist', stack_name)
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

    @staticmethod
    def get_filtered_stack_name(stack_name):
        return re.sub(r'[^0-9a-zA-Z]+', '', stack_name.title())

    def get_stack(self, stack_name):
        try:
            return self.cf_client.describe_stacks(StackName=stack_name)['Stacks'][0]
        except self.cf_client.exceptions.ClientError as e:
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
        existing_stack = {}
        try:
            existing_stack = self.cf_client.describe_stacks(StackName=stack_name).get('Stacks')[0]
            if (existing_stack['StackStatus'].startswith('DELETE') or
                    existing_stack['StackStatus'].startswith('ROLLBACK')):
                self._logger.error('Stack: %s has status: %s which is impossible to update', stack_name,
                                   existing_stack['StackStatus'])
                return existing_stack['StackId']

        except self.cf_client.exceptions.ClientError as e:
            if f'Stack with id {stack_name} does not exist' in str(e):
                self._logger.debug('%s: cloudformation stack does not exist', stack_name)
                return False

        params = params if params else []
        tags = tags if tags else []

        try:
            self.cf_client.update_stack(
                StackName=stack_name,
                Capabilities=['CAPABILITY_NAMED_IAM'],
                Parameters=params,
                TemplateBody=template_body,
                Tags=tags
            )
            self._logger.info('%s: updating stack', stack_name)
        except self.cf_client.exceptions.ClientError as e:
            if 'No updates are to be performed' in str(e):
                self._logger.info('%s: cloudformation stack update not required', stack_name)
                return existing_stack['StackId']
            else:
                raise

        result = self._wait_for_status(stack_name, 'UPDATE_COMPLETE', max_status_checks=max_status_checks,
                                       status_check_interval=status_check_interval)
        return existing_stack['StackId'] if result else False
