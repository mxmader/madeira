from madeira import kms, sts, session
from madeira_utils import loggers
import time


class Athena(object):

    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else loggers.get_logger()
        self._session = session.Session(logger=logger, profile_name=profile_name, region=region)
        self._sts = sts.Sts(logger=logger, profile_name=profile_name, region=region)

        self.athena_client = self._session.session.client('athena')
        self._kms = kms.Kms(logger=logger, profile_name=profile_name, region=region)
        self._logger = logger if logger else loggers.get_logger()
        self._max_query_checks = 10
        self._interval = 3

    def _get_default_output_location(self):
        return (f'aws-athena-query-results-{self._sts.account_id}-'
                f'{self._session.region}')

    def execute_query(self, database, sql, output_location=None, workgroup='primary'):
        if not output_location:
            output_location = self._get_default_output_location()
        self._logger.debug('Executing query: %s', sql)
        execution_id = self.athena_client.start_query_execution(
            QueryString=sql,
            QueryExecutionContext={'Database': database},
            ResultConfiguration={'OutputLocation': output_location},
            WorkGroup=workgroup
        ).get('QueryExecutionId')
        self._logger.debug('Query execution ID: %s', execution_id)

        # wait for query to complete and validate status
        # TODO: let waiting parameters be overridden at the method level
        for i in range(0, self._max_query_checks):

            execution_status = self.athena_client.get_query_execution(
                QueryExecutionId=execution_id).get('QueryExecution').get('Status')
            execution_state = execution_status.get('State')
            execution_state_reason = execution_status.get('StateChangeReason')

            if execution_state == 'SUCCEEDED':
                self._logger.info('Query %s successful', execution_id)
                break
            elif execution_state == 'FAILED':
                self._logger.critical('Query %s failed', execution_id)
                self._logger.critical('Reason: %s', execution_state_reason)
                break
            elif execution_state == 'CANCELLED':
                self._logger.error('Query %s was cancelled - human intervention?', execution_id)
                break

            time.sleep(self._interval)

    def update_workgroup(self, results_bucket=None, workgroup='primary', description='', requester_pays=False,
                         publish_cloudwatch=True, kms_key='alias/aws/s3'):
        if not results_bucket:
            results_bucket = self._get_default_output_location()

        # athena's API doesn't understand KMS key aliases, so we'll look up the ARN
        if kms_key == 'alias/aws/s3':
            self._logger.info('Looking up KMS key ARN for key: %s', kms_key)
            kms_key = self._kms.get_key(kms_key)['KeyMetadata']['Arn']
            self._logger.info('Got ARN: %s', kms_key)

        self._logger.info('Updating Athena default Workgroup configuration')
        return self.athena_client.update_work_group(
            WorkGroup=workgroup,
            Description=description,
            ConfigurationUpdates={
                'EnforceWorkGroupConfiguration': True,
                'ResultConfigurationUpdates': {
                    'OutputLocation': f's3://{results_bucket}/',
                    'EncryptionConfiguration': {
                        'EncryptionOption': 'SSE_KMS',
                        'KmsKey': kms_key
                    },
                },
                'PublishCloudWatchMetricsEnabled': publish_cloudwatch,
                'RequesterPaysEnabled': requester_pays
            },
            State='ENABLED'
        )
