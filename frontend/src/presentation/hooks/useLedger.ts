import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient
} from '@tanstack/react-query'

import {
  ledgerService,
  type LedgerClient,
  type LedgerMovement,
  type LedgerMovementPayload,
  type LedgerSummary
} from '@application/services/LedgerService'

export const useLedgerSummary = (enabled = true) =>
  useQuery<LedgerSummary>({
    queryKey: ['ledger-summary'],
    enabled,
    queryFn: () => ledgerService.getSummary()
  })

/** `q` del backend va de 2 a 80 caracteres: con menos, lista sin filtro. */
export const useLedgerClients = (search: string) => {
  const term = search.trim()
  const q = term.length >= 2 ? term : undefined
  return useQuery<LedgerClient[]>({
    queryKey: ['ledger-clients', q ?? null],
    // Con el signal, la busqueda vieja se cancela al tipear otra (F4-04).
    queryFn: ({ signal }) => ledgerService.searchClients(q, signal),
    placeholderData: keepPreviousData
  })
}

/**
 * Historial por paginas con cursor (FF-20). Devuelve la vista plana que usa
 * la pantalla; la clave sigue siendo ['customer-ledger', clientId] para que
 * la invalidacion de useAddLedgerMovement la alcance.
 */
export const useCustomerLedger = (clientId: string | null) => {
  const query = useInfiniteQuery({
    queryKey: ['customer-ledger', clientId],
    queryFn: ({ pageParam }) => ledgerService.getCustomerLedger(clientId as string, pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (page) => page.next_cursor ?? undefined,
    enabled: Boolean(clientId)
  })
  const pages = query.data?.pages ?? []
  return {
    balance: pages[0]?.balance,
    total: pages[0]?.total ?? 0,
    movements: pages.flatMap((page) => page.movements),
    hasNextPage: query.hasNextPage,
    fetchNextPage: query.fetchNextPage,
    isFetchingNextPage: query.isFetchingNextPage,
    isLoading: query.isLoading,
    error: query.error
  }
}

export const useAddLedgerMovement = () => {
  const queryClient = useQueryClient()
  return useMutation<LedgerMovement, Error, { clientId: string; payload: LedgerMovementPayload }>({
    mutationFn: ({ clientId, payload }) => ledgerService.addMovement(clientId, payload),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: ['ledger-summary'] })
      void queryClient.invalidateQueries({ queryKey: ['customer-ledger', variables.clientId] })
    }
  })
}

/**
 * Revierte un movimiento (decision de Mateo, 2026-10-03). Con exito o con
 * error se vuelve a pedir la cuenta: el saldo y la marca "Revertido" son del
 * servidor, y un 422 (ya revertido) quiere decir que la vista quedo vieja.
 */
export const useReverseLedgerMovement = () => {
  const queryClient = useQueryClient()
  return useMutation<LedgerMovement, Error, { clientId: string; movementId: string }>({
    mutationFn: ({ clientId, movementId }) => ledgerService.reverseMovement(clientId, movementId),
    onSettled: (_data, _error, variables) => {
      void queryClient.invalidateQueries({ queryKey: ['ledger-summary'] })
      void queryClient.invalidateQueries({ queryKey: ['customer-ledger', variables.clientId] })
    }
  })
}
