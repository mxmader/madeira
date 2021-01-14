from madeira import kms
import madeira
import boto3


class Glue(object):

    def __init__(self, logger=None, region=None):
        self.glue_client = boto3.client('glue', region_name=region)
        self._kms_wrapper = kms.Kms()
        self._logger = logger if logger else madeira.get_logger()

    def create_database(self, database):
        try:
            self._logger.info('Creating glue catalog database: %s', database)
            return self.glue_client.create_database(DatabaseInput={'Name': database})

        except self.glue_client.exceptions.AlreadyExistsException:
            self._logger.warning('Database already exists: %s', database)

    def create_or_update_job(self, name, role_arn, s3_script_path, description='', glue_version='1.0',
                             max_capacity=16,  max_retries=0, timeout_min=2880, worker_count=None,
                             worker_type=None, max_concurrent_runs=8, command_name='glueetl', default_arguments=None,
                             security_configuration=None):
        # TODO: docstring with explanation of mutually exclusive params
        job_params = dict(
            Name=name,
            Description=description,
            Role=role_arn,
            ExecutionProperty={
                'MaxConcurrentRuns': max_concurrent_runs
            },
            Command={
                'Name': command_name,
                'ScriptLocation': s3_script_path,
                'PythonVersion': '3'
            },

            # TODO: API doc doesn't really specify what to use here... may not be needed for S3-to-S3 ETL.
            # Connections={
            #     'Connections': [
            #         'string',
            #     ]
            # },

            MaxRetries=max_retries,
            Timeout=timeout_min,
            MaxCapacity=max_capacity,

            # TODO: API doc doesn't really specify what to use here... may not be needed for S3-to-S3 ETL.
            # SecurityConfiguration='string',

            # TODO: activate this if/when needed
            # NotificationProperty={
            #     'NotifyDelayAfter': 0
            # },
            GlueVersion=glue_version
        )

        if default_arguments:
            job_params['DefaultArguments'] = default_arguments

        if security_configuration:
            job_params['SecurityConfiguration'] = security_configuration

        if worker_type and worker_count:
            self._logger.warning('Since "max_capacity" is mutually exclusive to the combination of the "worker_type"'
                                 'and "worker_count" arguments, "max_capacity" is being dropped')
            job_params.update(dict(
                NumberOfWorkers=worker_count,
                WorkerType=worker_type
            ))
            del(job_params['MaxCapacity'])

        try:
            self.glue_client.get_job(JobName=name)
            self._logger.info('Glue Job: %s already exists; updating it', name)
            del(job_params['Name'])
            self.glue_client.update_job(JobName=name, JobUpdate=job_params)

        except self.glue_client.exceptions.EntityNotFoundException:
            self._logger.info('Creating Glue Job: %s', name)
            self.glue_client.create_job(**job_params)

        return name

    def create_or_update_table(self, database, name, glue_table):
        try:
            self.glue_client.get_table(DatabaseName=database, Name=name)
            self._logger.info('Updating table: %s', name)
            self.glue_client.update_table(**glue_table)
        except self.glue_client.exceptions.EntityNotFoundException:
            self._logger.info('Creating table: %s', name)
            self.glue_client.create_table(**glue_table)

    def delete_database(self, database):
        try:
            self._logger.info('Deleting glue database: %s', database)
            return self.glue_client.delete_database(Name=database)
        except self.glue_client.exceptions.EntityNotFoundException:
            self._logger.warning('Database does not exist: %s', database)
            return False

    def delete_job(self, job):
        return self.glue_client.delete_job(JobName=job)

    def delete_table(self, database, table):
        try:
            self._logger.info('Deleting glue table: %s', table)
            return self.glue_client.delete_table(DatabaseName=database, Name=table)
        except self.glue_client.exceptions.EntityNotFoundException:
            self._logger.warning('Either database: %s or table: %s does not exist', database, table)
            return False

    def list_jobs(self):
        # get the largest chunk possible according to AWS API limits
        max_results = 100
        glue_jobs = list()

        self._logger.debug('Reading first chunk of glue jobs')
        glue_job_chunk = self.glue_client.list_jobs(
            MaxResults=max_results
        )
        glue_jobs.extend(glue_job_chunk.get('JobNames'))

        while glue_job_chunk.get('NextToken'):
            self._logger.debug('Reading next chunk of glue jobs')
            glue_job_chunk = self.glue_client.list_jobs(
                NextToken=glue_job_chunk.get('NextToken'),
                MaxResults=max_results
            )
            glue_jobs.extend(glue_job_chunk.get('JobNames'))
        return glue_jobs

    def list_tables(self, database):
        try:
            return self.glue_client.get_tables(DatabaseName=database, MaxResults=999).get('TableList')
        except self.glue_client.exceptions.EntityNotFoundException:
            return []
