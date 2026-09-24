import { useQuery } from '@tanstack/react-query'

import { userAdminService, type ManagedUser } from '@application/services/UserAdminService'

export const useManagedUsers = (includeInactive = false) =>
  useQuery({
    queryKey: ['users', includeInactive],
    queryFn: (): Promise<ManagedUser[]> => userAdminService.list(includeInactive)
  })
