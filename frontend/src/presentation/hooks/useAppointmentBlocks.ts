import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  appointmentBlocksService,
  type AppointmentBlock,
  type AppointmentBlockListParams,
  type AppointmentBlockPayload,
  type AppointmentBlockUpdatePayload,
  type BlockPreviewPayload,
  type BlockPreviewResult,
  type BlockTemplate,
  type RecurringAppointmentBlockPayload,
  type RecurringBlocksResult
} from '@application/services/AppointmentBlocksService'

// Un bloqueo puede cancelar turnos: la agenda tambien tiene que refrescarse.
const BLOCK_QUERIES = [['appointment-blocks'], ['calendar-agenda']] as const

/**
 * Bloqueos ACTIVOS del rango visible (F4-07, FF-12): antes se traia toda la
 * historia de la tienda, activos e inactivos, y se filtraba en memoria. La
 * clave empieza con 'appointment-blocks', asi que invalidar ese prefijo
 * (BLOCK_QUERIES) sigue refrescando todos los rangos.
 */
export const useAppointmentBlocks = (fromDate: string, toDate: string) => {
  const params: AppointmentBlockListParams = {
    from_date: fromDate,
    to_date: toDate,
    include_inactive: false
  }
  return useQuery<AppointmentBlock[]>({
    queryKey: ['appointment-blocks', fromDate, toDate],
    queryFn: () => appointmentBlocksService.list(params),
    enabled: Boolean(fromDate && toDate),
    // Al cambiar de dia o de vista, los bloqueos del rango anterior quedan
    // hasta que llegan los nuevos en vez de parpadear vacios.
    placeholderData: keepPreviousData
  })
}

/** Recepcion recibe 403 en las plantillas: no se piden (D-20260929-09). */
export const useBlockTemplates = ({ enabled }: { enabled: boolean }) =>
  useQuery<BlockTemplate[]>({
    queryKey: ['appointment-block-templates'],
    queryFn: () => appointmentBlocksService.getTemplates(),
    enabled
  })

export const useCreateAppointmentBlock = () => {
  const queryClient = useQueryClient()
  return useMutation<AppointmentBlock, Error, AppointmentBlockPayload>({
    mutationFn: (payload) => appointmentBlocksService.create(payload),
    onSuccess: () => {
      BLOCK_QUERIES.forEach((queryKey) => {
        void queryClient.invalidateQueries({ queryKey: [...queryKey] })
      })
    }
  })
}

export const useCreateRecurringAppointmentBlock = () => {
  const queryClient = useQueryClient()
  return useMutation<RecurringBlocksResult, Error, RecurringAppointmentBlockPayload>({
    mutationFn: (payload) => appointmentBlocksService.createRecurring(payload),
    onSuccess: () => {
      BLOCK_QUERIES.forEach((queryKey) => {
        void queryClient.invalidateQueries({ queryKey: [...queryKey] })
      })
    }
  })
}

export const useUpdateAppointmentBlock = () => {
  const queryClient = useQueryClient()
  return useMutation<
    AppointmentBlock,
    Error,
    { publicId: string; payload: AppointmentBlockUpdatePayload }
  >({
    mutationFn: ({ publicId, payload }) => appointmentBlocksService.update(publicId, payload),
    onSuccess: () => {
      BLOCK_QUERIES.forEach((queryKey) => {
        void queryClient.invalidateQueries({ queryKey: [...queryKey] })
      })
    }
  })
}

export const useDeleteAppointmentBlock = () => {
  const queryClient = useQueryClient()
  return useMutation<void, Error, string>({
    mutationFn: (publicId) => appointmentBlocksService.delete(publicId),
    onSuccess: () => {
      BLOCK_QUERIES.forEach((queryKey) => {
        void queryClient.invalidateQueries({ queryKey: [...queryKey] })
      })
    }
  })
}

export const useBlockPreview = () =>
  useMutation<BlockPreviewResult, Error, BlockPreviewPayload>({
    mutationFn: (payload) => appointmentBlocksService.preview(payload)
  })
