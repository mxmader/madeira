import time

from madeira_utils import hashing, loggers, utils
from madeira import session, sts


class AwsLambda:

    def __init__(self, logger=None, profile_name=None, region=None):
        self._logger = logger if logger else loggers.get_logger()
        self._session = session.Session(logger=logger, profile_name=profile_name, region=region)
        self._sts = sts.Sts(logger=logger, profile_name=None, region=None)

        self.lambda_client = self._session.session.client('lambda')

    def _create_function(self, name, role, function_file_path, description='', vpc_config=None, memory_size=128,
                         timeout=30, reserved_concurrency=None, layer_arns=None, runtime='python3.8',
                         handler='handler.handler'):
        layer_arns = layer_arns if layer_arns else []
        vpc_config = vpc_config if vpc_config else {}

        self._logger.info('Deploying function: %s from file: %s', name, function_file_path)
        try:
            function_arn = self.lambda_client.create_function(
                FunctionName=name,
                Runtime=runtime,
                Role=role,
                Handler=handler,
                Code={'ZipFile': utils.get_zip_content(function_file_path)},
                Description=description,
                Timeout=timeout,
                Layers=layer_arns,
                MemorySize=memory_size,
                Publish=True,
                VpcConfig=vpc_config).get('FunctionArn')

        except self.lambda_client.exceptions.ResourceConflictException:
            self._logger.warning('Function: %s already exists', name)
            function_arn = self.lambda_client.get_function(FunctionName=name).get('Configuration').get('FunctionArn')

        if reserved_concurrency:
            self._set_reserved_concurrency(name, reserved_concurrency)

        return function_arn

    def _set_reserved_concurrency(self, name, reserved_concurrency):
        if reserved_concurrency:
            self._logger.info('setting reserved concurrency to %s on function %s', reserved_concurrency, name)
            self.lambda_client.put_function_concurrency(
                FunctionName=name, ReservedConcurrentExecutions=reserved_concurrency)

    def _update_function(self, name, role, function_file_path, description='', vpc_config=None, memory_size=128,
                         timeout=30, reserved_concurrency=None, layer_arns=None, runtime='python-3.8',
                         handler='handler.handler'):
        layer_arns = layer_arns if layer_arns else []
        vpc_config = vpc_config if vpc_config else {}

        self._logger.info('%s: updating lambda function code', name)
        self.lambda_client.update_function_code(
            FunctionName=name,
            ZipFile=utils.get_zip_content(function_file_path),
            Publish=True
        )
        self._logger.info('%s: updating lambda function configuration', name)
        self.lambda_client.update_function_configuration(
            FunctionName=name,
            Runtime=runtime,
            Role=role,
            Handler=handler,
            Description=description,
            VpcConfig=vpc_config,
            Timeout=timeout,
            MemorySize=memory_size,
            Layers=layer_arns
        )

        if reserved_concurrency:
            self._set_reserved_concurrency(name, reserved_concurrency)

    def _wait_for_availability(self, function_arn):
        max_status_checks = 10
        status_check_interval = 20

        # wait for stack "final" state
        status_check = 0
        finished_status = 'Active'

        while status_check < max_status_checks:
            status_check += 1
            lambda_function = self.lambda_client.get_function(FunctionName=function_arn)

            if lambda_function['Configuration']['State'] == finished_status:
                self._logger.debug(
                    "Lambda function %s is now: %s", lambda_function["Configuration"]["FunctionName"], finished_status
                )
                return

            self._logger.debug(
                "Lambda function: %s status is: %s - waiting for status: %s",
                lambda_function["Configuration"]["FunctionName"],
                lambda_function['Configuration']['State'],
                finished_status)

            if status_check >= max_status_checks:
                raise RuntimeError(
                    "Timed out waiting for lambda function: %s to be available",
                    lambda_function["Configuration"]["FunctionName"])

            time.sleep(status_check_interval)

    def add_permission_for_s3_bucket(self, name, bucket):
        self.remove_permission_for_s3_bucket(name, bucket)
        self._logger.info('Allowing invocation of function: %s based on events from S3 bucket: %s', name, bucket)
        self.lambda_client.add_permission(
            Action='lambda:InvokeFunction',
            FunctionName=name,
            Principal='s3.amazonaws.com',
            SourceAccount=self._sts.account_id,
            SourceArn=f'arn:aws:s3:::{bucket}',
            StatementId=f'permission_for_{bucket}'
        )

    def create_or_update_function(self, name, role, function_file_path, description='', vpc_config=None,
                                  memory_size=128, timeout=30, reserved_concurrency=None, layers=None,
                                  runtime='python3.8', handler='handler.handler'):
        if layers:
            layer_arns = [layer_meta['arn'] for name, layer_meta in layers.items()]
            layers_updated = [name for name, layer_meta in layers.items() if layer_meta['updated']]
        else:
            layer_arns = []
            layers_updated = []

        try:
            lambda_function = self.lambda_client.get_function(FunctionName=name)
            self._logger.debug('%s: lambda function: already exists; checking on updates', name)
            function_arn = lambda_function['Configuration']['FunctionArn']
            existing_layers = [layer['Arn'] for layer in lambda_function['Configuration']['Layers']]
            added_layers = [layer_arn for layer_arn in layer_arns if layer_arn not in existing_layers]
            removed_layers = [layer_arn for layer_arn in existing_layers if layer_arn not in layer_arns]

            # Calculate the SHA256 checksum of the file (whether a zip file or not)
            file_sha256_string = utils.get_base64_sum_of_file(function_file_path)

            if function_file_path.endswith('.zip'):
                aws_file_sha256_string = lambda_function.get('Configuration').get('CodeSha256')
            else:
                # AWS stores lambdas in zip files in a "hidden" S3 bucket - we need to extract the handler as-stored
                # in S3 in order to compare it to our local file. This reads the whole encapsulating zip in memory;
                # we're assuming all lambdas stay relatively small
                aws_file_sha256_string = utils.get_base64_sum_of_file_in_zip_from_url(
                    lambda_function.get('Code').get('Location'), 'handler.py')

            if file_sha256_string != aws_file_sha256_string:
                self._logger.info('%s: updating lambda function for intrinsic code change', name)
            elif layers_updated:
                self._logger.info(
                    '%s: updating lambda only for code changed in related layers: %s', name, layers_updated)
            elif added_layers or removed_layers:
                if added_layers:
                    self._logger.info('%s: updating lambda function for added layers: %s', name, added_layers)
                if removed_layers:
                    self._logger.info('%s: updating lambda function for removed layers: %s', name, removed_layers)
            else:
                self._logger.info('%s: no lambda function code nor related layer changes; no update required', name)
                return function_arn

            self._update_function(
                name, role, function_file_path, description=description, vpc_config=vpc_config, memory_size=memory_size,
                timeout=timeout, reserved_concurrency=reserved_concurrency, layer_arns=layer_arns, runtime=runtime,
                handler=handler)

        except self.lambda_client.exceptions.ResourceNotFoundException:
            self._logger.info('Function: %s does not yet exist', name)
            function_arn = self._create_function(
                name, role, function_file_path, description=description, vpc_config=vpc_config, memory_size=memory_size,
                timeout=timeout, reserved_concurrency=reserved_concurrency, layer_arns=layer_arns, runtime=runtime,
                handler=handler)

        # VPC-scoped lambdas sometimes take more time to spin up, so we wait for their final state
        if vpc_config:
            self._wait_for_availability(function_arn)

        return function_arn

    def delete_function(self, name, qualifier=None):
        args = {'FunctionName': name}
        if qualifier:
            args['Qualifier'] = qualifier

        try:
            self.lambda_client.delete_function(**args)
            self._logger.info('Function: %s deleted', name)
        except self.lambda_client.exceptions.ResourceNotFoundException:
            self._logger.warning('Function: %s does not exist', name)

    def delete_layer_version(self, name, version):
        try:
            self.lambda_client.delete_layer_version(LayerName=name, VersionNumber=version)
            self._logger.info('Layer: %s version: %s deleted', name, version)
        except self.lambda_client.exceptions.ResourceNotFoundException:
            self._logger.warning('Layer: %s version: %s does not exist', name, version)

    def deploy_layer(self, name, layer_path, description='', runtimes=None):
        # for layers with more complexity that are better off "just zipped"
        if layer_path.endswith('.zip'):
            with open(layer_path, 'rb') as f:
                zip_file_bytes = f.read()

        # for layers that consist simply of a flat directory (no subdirs) with code (text) files.
        else:
            in_memory_zip = utils.get_layer_zip(layer_path)
            zip_file_bytes = in_memory_zip.getvalue()

        file_sha256_string = hashing.get_base64_sum_of_data(zip_file_bytes)

        for lambda_layer_version in self.list_layer_versions(name):
            layer_version_meta = self.lambda_client.get_layer_version_by_arn(
                Arn=lambda_layer_version['LayerVersionArn'])
            aws_sha256_string = layer_version_meta['Content']['CodeSha256']
            if aws_sha256_string == file_sha256_string:
                self._logger.info('Layer with ARN: %s is already current', lambda_layer_version['LayerVersionArn'])
                return {'arn': lambda_layer_version['LayerVersionArn'], 'updated': False}

        if not runtimes:
            runtimes = ['python3.8']

        self._logger.info('Deploying layer: %s in path: %s for runtimes: %s', name, layer_path, runtimes)
        layer_arn = self.lambda_client.publish_layer_version(
            LayerName=name,
            Description=description,
            # must be a 'bytes' object
            Content={'ZipFile': zip_file_bytes},
            CompatibleRuntimes=runtimes).get('LayerVersionArn')
        self._logger.debug('Layer ARN: %s', layer_arn)
        return {'arn': layer_arn, 'updated': True}

    def deploy_layers(self, layers):
        for name, layer_meta in layers.items():
            layers[name].update(self.deploy_layer(name, layer_meta['path']))

    def get_function_arn(self, name):
        return f"arn:aws:lambda:{self._session.region}:{self._sts.account_id}:function:{name}"

    def list_functions(self):
        response = self.lambda_client.list_functions()
        functions = response.get('Functions')

        while response.get('NextMarker'):
            response = self.lambda_client.list_functions(NextMarker=response.get('NextMarker'))
            functions.extend(response.get('Functions'))

        return functions

    def list_layers(self):
        return self.lambda_client.list_layers().get('Layers')

    def list_layer_versions(self, name):
        response = self.lambda_client.list_layer_versions(LayerName=name)
        layer_versions = response.get('LayerVersions')

        while response.get('NextMarker'):
            response = self.lambda_client.list_layer_versions(LayerName=name, NextMarker=response.get('NextMarker'))
            layer_versions.extend(response.get('LayerVersions'))

        return layer_versions

    def remove_permission_for_s3_bucket(self, name, bucket):
        self._logger.info('Attempting to remove permission to invoke function: %s based on events from S3 bucket: %s '
                          'if any', name, bucket)
        try:
            self.lambda_client.remove_permission(FunctionName=name, StatementId=f'permission_for_{bucket}')
        # NOTE: there's no clean way to first look up if a permission exists before removing it without re-arranging
        # this module, so for now we just catch the exception and move on.
        except self.lambda_client.exceptions.ResourceNotFoundException:
            self._logger.warning('Permission does not yet exist to invoke function: %s based on events from '
                                 'S3 bucket: %s', name, bucket)
