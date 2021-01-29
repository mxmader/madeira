import time

from madeira import session, sts
from madeira_utils import loggers


class StepFunctions:

    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else loggers.get_logger()
        self._session = session.Session(logger=logger, profile_name=profile_name, region=region)
        self._sts = sts.Sts(logger=logger, profile_name=None, region=None)

        self.step_functions_client = self._session.session.client('stepfunctions')

    def create_state_machine(self, name, definition, role_arn, attempt=1):
        if attempt > 10:
            self._logger.error('Exhausted %s attempts to deploy state machine: %s', attempt, name)
            return False

        self._logger.debug('Attempt: %s to deploy state machine: %s', attempt, name)
        try:
            result = self.step_functions_client.create_state_machine(name=name, definition=definition, roleArn=role_arn)
            self._logger.info('Created state machine: %s', name)
            return result
        except self.step_functions_client.exceptions.StateMachineDeleting:
            self._logger.warning('State machine: %s is still in the process of deleting', name)
            self._logger.info('Waiting a while for that process to finish')
            time.sleep(10)

            return self.create_state_machine(name, definition, role_arn, attempt=attempt+1)

    def create_or_update_state_machine(self, name, definition, role_arn):
        try:
            state_machine_arn = (f'arn:aws:states:{self._session.region}:'
                                 f'{self._sts.account_id}:stateMachine:{name}')
            state_machine = self.step_functions_client.describe_state_machine(stateMachineArn=state_machine_arn)
            if state_machine['status'] == 'DELETING':
                return self.create_state_machine(name, definition, role_arn)
            return self.update_state_machine(state_machine_arn, definition, role_arn)
        except self.step_functions_client.exceptions.StateMachineDoesNotExist:
            return self.create_state_machine(name, definition, role_arn)

    def delete_state_machine(self, arn):
        self.step_functions_client.delete_state_machine(stateMachineArn=arn)

    def list_state_machines(self):
        return self.step_functions_client.list_state_machines().get('stateMachines')

    def wait_for_executions(self, state_machine_arn, wait_interval=60):
        max_retries = 60
        count = 0
        while True:
            count += 1
            response = self.step_functions_client.list_executions(
                stateMachineArn=state_machine_arn, statusFilter='RUNNING')
            execution_arns = [execution['executionArn'] for execution in response.get('executions')]

            if execution_arns:
                if count == max_retries:
                    self._logger.error('Timed out waiting for state machine executions to finish:')
                    for execution_arn in execution_arns:
                        self._logger.error('  %s', execution_arn)
                    return

                self._logger.info('Waiting %s sec for state machine executions to finish:', wait_interval)
                for execution_arn in execution_arns:
                    self._logger.info('  %s', execution_arn)
                time.sleep(wait_interval)
            else:
                self._logger.info('State machine executions of %s completed', state_machine_arn)
                return

    def update_state_machine(self, state_machine_arn, definition, role_arn):
        result = self.step_functions_client.update_state_machine(
            stateMachineArn=state_machine_arn,
            definition=definition,
            roleArn=role_arn
        )
        self._logger.info('Updated state machine: %s', state_machine_arn)
        return result
