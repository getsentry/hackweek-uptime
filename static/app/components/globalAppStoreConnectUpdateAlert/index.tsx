import * as AppStoreConnectContext from 'sentry/components/projects/appStoreConnectContext';
import {Organization, Project} from 'sentry/types';

import UpdateAlert from './updateAlert';

type Props = Pick<
  React.ComponentProps<typeof UpdateAlert>,
  'isCompact' | 'className' | 'Wrapper'
> & {
  organization: Organization;
  project?: Project;
};

function GlobalAppStoreConnectUpdateAlert({project, organization, ...rest}: Props) {
  return (
    <AppStoreConnectContext.Provider project={project} organization={organization}>
      <UpdateAlert project={project} organization={organization} {...rest} />
    </AppStoreConnectContext.Provider>
  );
}

export default GlobalAppStoreConnectUpdateAlert;
