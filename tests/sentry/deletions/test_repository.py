from unittest.mock import patch

from django.core import mail

from sentry.constants import ObjectStatus
from sentry.exceptions import PluginError
from sentry.models import (
    Commit,
    Integration,
    OrganizationOption,
    ProjectCodeOwners,
    Repository,
    RepositoryProjectPathConfig,
)
from sentry.silo.base import SiloMode
from sentry.tasks.deletion.scheduled import run_scheduled_deletions
from sentry.testutils.cases import TransactionTestCase
from sentry.testutils.hybrid_cloud import HybridCloudTestMixin
from sentry.testutils.silo import assume_test_silo_mode, region_silo_test


@region_silo_test(stable=True)
class DeleteRepositoryTest(TransactionTestCase, HybridCloudTestMixin):
    def test_simple(self):
        org = self.create_organization()
        repo = Repository.objects.create(
            organization_id=org.id,
            provider="dummy",
            name="example/example",
            status=ObjectStatus.PENDING_DELETION,
        )
        repo2 = Repository.objects.create(
            organization_id=org.id, provider="dummy", name="example/example2"
        )
        commit = Commit.objects.create(
            repository_id=repo.id, organization_id=org.id, key="1234abcd"
        )
        commit2 = Commit.objects.create(
            repository_id=repo2.id, organization_id=org.id, key="1234abcd"
        )

        self.ScheduledDeletion.schedule(instance=repo, days=0)

        with self.tasks():
            run_scheduled_deletions()

        assert not Repository.objects.filter(id=repo.id).exists()
        assert not Commit.objects.filter(id=commit.id).exists()
        assert Commit.objects.filter(id=commit2.id).exists()

    def test_codeowners(self):
        org = self.create_organization(owner=self.user)
        with assume_test_silo_mode(SiloMode.CONTROL):
            self.integration = Integration.objects.create(
                provider="github", name="Example", external_id="abcd"
            )
            org_integration = self.integration.add_organization(org, self.user)
        project = self.create_project(organization=org)
        repo = Repository.objects.create(
            organization_id=org.id,
            provider="dummy",
            name="example/example",
            status=ObjectStatus.PENDING_DELETION,
        )
        path_config = RepositoryProjectPathConfig.objects.create(
            project=project,
            repository=repo,
            stack_root="",
            source_root="src/packages/store",
            default_branch="main",
            organization_integration_id=org_integration.id,
        )
        code_owner = ProjectCodeOwners.objects.create(
            project=project,
            repository_project_path_config=path_config,
            raw="* @org/devs",
        )
        self.ScheduledDeletion.schedule(instance=repo, days=0)

        with self.tasks():
            run_scheduled_deletions()

        assert not Repository.objects.filter(id=repo.id).exists()
        assert not RepositoryProjectPathConfig.objects.filter(id=path_config.id).exists()
        assert not ProjectCodeOwners.objects.filter(id=code_owner.id).exists()

    def test_no_delete_visible(self):
        org = self.create_organization()
        repo = Repository.objects.create(
            organization_id=org.id, provider="dummy", name="example/example"
        )
        self.ScheduledDeletion.schedule(instance=repo, days=0)

        with self.tasks():
            run_scheduled_deletions()
        assert Repository.objects.filter(id=repo.id).exists()

    @patch("sentry.plugins.providers.dummy.repository.DummyRepositoryProvider.delete_repository")
    def test_delete_fail_email(self, mock_delete_repo):
        mock_delete_repo.side_effect = PluginError("foo")

        org = self.create_organization()
        repo = Repository.objects.create(
            organization_id=org.id,
            provider="dummy",
            name="example/example",
            status=ObjectStatus.PENDING_DELETION,
        )

        self.ScheduledDeletion.schedule(instance=repo, actor=self.user, days=0)

        with self.tasks():
            run_scheduled_deletions()

        msg = mail.outbox[-1]
        assert msg.subject == "Unable to Delete Repository Webhooks"
        assert msg.to == [self.user.email]
        assert "foo" in msg.body
        assert not Repository.objects.filter(id=repo.id).exists()

    @patch("sentry.plugins.providers.dummy.repository.DummyRepositoryProvider.delete_repository")
    def test_delete_fail_email_random(self, mock_delete_repo):
        mock_delete_repo.side_effect = Exception("secrets")

        org = self.create_organization()
        repo = Repository.objects.create(
            organization_id=org.id,
            provider="dummy",
            name="example/example",
            status=ObjectStatus.PENDING_DELETION,
        )

        self.ScheduledDeletion.schedule(instance=repo, actor=self.user, days=0)

        with self.tasks():
            run_scheduled_deletions()

        msg = mail.outbox[-1]
        assert msg.subject == "Unable to Delete Repository Webhooks"
        assert msg.to == [self.user.email]
        assert "secrets" not in msg.body
        assert not Repository.objects.filter(id=repo.id).exists()

    def test_botched_deletion(self):
        repo = Repository.objects.create(
            organization_id=self.organization.id,
            provider="dummy",
            name="example/example",
            status=ObjectStatus.PENDING_DELETION,
        )
        # Left over from a botched deletion.
        OrganizationOption.objects.create(
            organization_id=self.organization.id,
            key=repo.build_pending_deletion_key(),
            value="",
        )

        self.ScheduledDeletion.schedule(instance=repo, days=0)

        with self.tasks():
            run_scheduled_deletions()

        assert not Repository.objects.filter(id=repo.id).exists()
