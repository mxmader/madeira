import madeira
import boto3
import time


class Acm(object):

    def __init__(self, logger=None, profile_name=None, region=None):
        self._session = boto3.session.Session(
            profile_name=profile_name, region_name=region
        )
        self.acm_client = self._session.client('acm')
        self._logger = logger if logger else madeira.get_logger()
        self._max_status_checks = 20
        self._status_check_interval = 20

    def delete_cert_by_domain_name(self, domain_name):
        certificate_arn = self.get_cert_arn_by_domain(domain_name)
        if not certificate_arn:
            self._logger.warning("No ACM certificate exists for domain: %s", domain_name)
            return

        self._logger.info("Deleting certificate for domain: %s with ARN: %s", domain_name, certificate_arn)
        return self.acm_client.delete_certificate(CertificateArn=certificate_arn)

    def get_cert_arn_by_domain(self, domain_name):
        for cert in self.acm_client.list_certificates().get('CertificateSummaryList'):
            if cert['DomainName'] == domain_name:
                return cert['CertificateArn']

    def request_cert_dns_validation(self, domain_name):
        # check if cert has already been requested
        certificate_arn = self.get_cert_arn_by_domain(domain_name)
        if certificate_arn:
            self._logger.info('Certificate with domain: %s has already been requested', domain_name)
        else:
            self._logger.info('Requesting ACM cert with domain name: %s', domain_name)
            certificate_arn = self.acm_client.request_certificate(
                DomainName=domain_name,
                ValidationMethod='DNS').get('CertificateArn')

        self._logger.debug('Got certificate ARN: %s', certificate_arn)
        time.sleep(10)
        return certificate_arn, self.acm_client.describe_certificate(
            CertificateArn=certificate_arn).get('Certificate').get(
                'DomainValidationOptions')[0].get('ResourceRecord')

    def wait_for_issuance(self, certificate_arn):
        max_status_checks = 30
        status_check_interval = 60

        # wait for certificate issuance
        status_check = 0
        self._logger.info('Waiting on ACM certificate issuance confirmation. This may take up to 30 minutes...')

        while status_check < max_status_checks:
            status_check += 1

            # look for our cert to be in the ISSUED state.
            for cert in self.acm_client.list_certificates(
                    CertificateStatuses=['ISSUED']).get('CertificateSummaryList'):
                if cert['CertificateArn'] == certificate_arn:
                    self._logger.info('Certificate: %s is now issued', certificate_arn)
                    return True

            self._logger.debug('Certificate: %s is not yet issued - waiting', certificate_arn)

            if status_check >= max_status_checks:
                raise RuntimeError(f'Timed out waiting for Certificate {certificate_arn} to be issued')

            time.sleep(status_check_interval)
