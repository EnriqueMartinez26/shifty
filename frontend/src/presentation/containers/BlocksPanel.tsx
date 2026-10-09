import React, { useState } from 'react'

import type { BlockPreviewResult } from '@application/services/AppointmentBlocksService'

import { getErrorCode, getErrorMessage } from '@shared/errors/getErrorMessage'
import {
  argentinaLocalToUtcIso,
  formatArgentinaDate,
  formatArgentinaTime
} from '@shared/utils/argentinaTime'

import { BlockForm, type BlockFormState } from '../components/organisms/BlockForm'
import { BlockPreviewModal } from '../components/organisms/BlockPreviewModal'
import {
  useBlockPreview,
  useBlockTemplates,
  useCreateAppointmentBlock,
  useCreateRecurringAppointmentBlock,
  useUpdateAppointmentBlock
} from '../hooks/useAppointmentBlocks'
import { useStoreWriteAccess } from '../hooks/useStoreWriteAccess'
import {
  MAX_BLOCK_OCCURRENCES,
  addCalendarDays,
  countOccurrences,
  type BlockRecurrence
} from '../lib/blockRecurrence'

/** Bloqueo a editar, con los instantes en ISO UTC como los manda la API. */
export interface EditableBlock {
  public_id: string
  staff_id: string
  starts_at: string
  ends_at: string
  reason: string
}

interface BlocksPanelProps {
  staffMembers: readonly { id: string; displayName: string }[] | undefined
  /** Dia que muestra el calendario (`yyyy-MM-dd`); el bloqueo nuevo lo sigue. */
  dateStr: string
  /** Gestionar bloqueos: admin y profesional (D-20260929-08/09). */
  canManageBlocks: boolean
  /** Cancelar turnos en bloque: solo administradores (FF-34). */
  canCancelAffected: boolean
  /** El contenedor remonta el panel con `key` al cambiar de bloqueo. */
  editTarget: EditableBlock | null
  onDoneEditing: () => void
  onMessage: (message: string) => void
}

interface BlockRequest {
  staffId: string
  startsAt: string
  endsAt: string
  reason: string
  recurrence: BlockRecurrence
  recurrenceUntil: string | undefined
  occurrences: number
}

const SAVE_ERROR = 'No se pudo guardar el bloqueo'

const initialForm = (editTarget: EditableBlock | null, staffId = ''): BlockFormState =>
  editTarget
    ? {
        staff_id: editTarget.staff_id,
        date: formatArgentinaDate(editTarget.starts_at),
        starts_at: formatArgentinaTime(editTarget.starts_at),
        ends_at: formatArgentinaTime(editTarget.ends_at),
        reason: editTarget.reason,
        recurrence: 'none',
        recurrence_until: null
      }
    : {
        staff_id: staffId,
        date: null,
        starts_at: '10:00',
        ends_at: '11:00',
        reason: 'No atender',
        recurrence: 'none',
        recurrence_until: null
      }

interface BlockEditorOptions {
  editTarget: EditableBlock | null
  onCreated: () => void
  onDoneEditing: () => void
  onMessage: (message: string) => void
}

/** Las tres escrituras del panel y la vista previa, con sus avisos. */
const useBlockMutations = ({ onCreated, onDoneEditing, onMessage }: BlockEditorOptions) => {
  const previewBlock = useBlockPreview()
  const createBlock = useCreateAppointmentBlock()
  const createRecurringBlock = useCreateRecurringAppointmentBlock()
  const updateBlock = useUpdateAppointmentBlock()

  const update = async (target: EditableBlock, request: BlockRequest, cancelAffected: boolean) => {
    await updateBlock.mutateAsync({
      publicId: target.public_id,
      payload: {
        starts_at: request.startsAt,
        ends_at: request.endsAt,
        reason: request.reason,
        ...(cancelAffected ? { cancel_affected: true } : {})
      }
    })
    onMessage(cancelAffected ? 'Bloqueo actualizado y turnos cancelados' : 'Bloqueo actualizado')
    onDoneEditing()
  }

  const create = async (request: BlockRequest, cancelAffected: boolean) => {
    const base = {
      staff_id: request.staffId,
      starts_at: request.startsAt,
      ends_at: request.endsAt,
      reason: request.reason,
      cancel_affected: cancelAffected
    }
    if (request.recurrence === 'none') {
      await createBlock.mutateAsync(base)
      onMessage(cancelAffected ? 'Bloqueo creado y turnos cancelados' : 'Bloqueo creado')
    } else {
      await createRecurringBlock.mutateAsync({
        ...base,
        recurrence: request.recurrence,
        recurrence_until: request.recurrenceUntil,
        max_occurrences: Math.min(request.occurrences, MAX_BLOCK_OCCURRENCES)
      })
      onMessage(
        cancelAffected ? 'Serie de bloqueos creada y turnos cancelados' : 'Serie de bloqueos creada'
      )
    }
    onCreated()
  }

  const preview = (request: BlockRequest) =>
    previewBlock.mutateAsync({
      staff_id: request.staffId,
      starts_at: request.startsAt,
      ends_at: request.endsAt,
      recurrence: request.recurrence,
      ...(request.recurrence === 'none'
        ? {}
        : {
            recurrence_until: request.recurrenceUntil,
            max_occurrences: Math.min(request.occurrences, MAX_BLOCK_OCCURRENCES)
          })
    })

  const busy = createBlock.isPending || createRecurringBlock.isPending || updateBlock.isPending
  return { update, create, preview, busy, saving: busy || previewBlock.isPending }
}

/**
 * Alta y edicion con vista previa de turnos afectados. La edicion no tiene
 * `/preview` propio en el flujo feliz: si el rango nuevo pisa turnos, el PATCH
 * responde 409 BLOCK_HAS_APPOINTMENTS y recien ahi se pide la vista previa
 * (FF-11). El PATCH no lleva `staff_id` (D-20260929-11).
 */
const useBlockEditor = (options: BlockEditorOptions) => {
  const { editTarget, onMessage } = options
  const { update, create, preview, busy, saving } = useBlockMutations(options)
  const [pending, setPending] = useState<{
    preview: BlockPreviewResult
    request: BlockRequest
  } | null>(null)

  const previewAfterConflict = async (request: BlockRequest, conflict: unknown) => {
    try {
      const result = await preview(request)
      if (result.affected.length > 0) setPending({ preview: result, request })
      else onMessage(getErrorMessage(conflict, SAVE_ERROR))
    } catch (error: unknown) {
      onMessage(getErrorMessage(error, SAVE_ERROR))
    }
  }

  const save = async (request: BlockRequest) => {
    try {
      if (editTarget) {
        await update(editTarget, request, false)
        return
      }
      // Antes de bloquear: que turnos quedan adentro. Si hay, se ven y se
      // confirma la cancelacion en bloque; el backend responde 409 sin eso.
      const result = await preview(request)
      if (result.affected.length > 0) {
        setPending({ preview: result, request })
        return
      }
      await create(request, false)
    } catch (error: unknown) {
      if (editTarget && getErrorCode(error) === 'BLOCK_HAS_APPOINTMENTS') {
        await previewAfterConflict(request, error)
        return
      }
      onMessage(getErrorMessage(error, SAVE_ERROR))
    }
  }

  const confirm = async () => {
    if (!pending) return
    try {
      if (editTarget) await update(editTarget, pending.request, true)
      else await create(pending.request, true)
      setPending(null)
    } catch (error: unknown) {
      onMessage(getErrorMessage(error, SAVE_ERROR))
    }
  }

  return {
    pending,
    busy,
    saving,
    save,
    confirm,
    dismiss: () => setPending(null)
  }
}

/**
 * Formulario de bloqueos de la agenda, fuera de CalendarContainer (F4-08).
 * Recepcion ve los bloqueos en la agenda pero no los gestiona
 * (D-20260929-09): no se muestra el formulario ni se piden las plantillas,
 * que le responden 403.
 */
export const BlocksPanel: React.FC<BlocksPanelProps> = (props) => {
  const { staffMembers, dateStr, canManageBlocks, editTarget } = props
  const [form, setForm] = useState<BlockFormState>(() => initialForm(editTarget))
  const templatesQuery = useBlockTemplates({ enabled: canManageBlocks })
  // Tienda suspendida: /preview, /, /batch y el PATCH responden 402 (FF-15).
  const writeAccess = useStoreWriteAccess()
  const readOnlyReason = writeAccess.readOnly ? writeAccess.reason : null
  const editor = useBlockEditor({
    editTarget,
    onCreated: () => setForm((prev) => initialForm(null, prev.staff_id)),
    onDoneEditing: props.onDoneEditing,
    onMessage: props.onMessage
  })
  if (!canManageBlocks) return null

  // Sin efecto que sincronice: el profesional por defecto se calcula aca (regla 27).
  const staffId = editTarget?.staff_id ?? (form.staff_id || staffMembers?.[0]?.id || '')
  const blockDate = form.date ?? dateStr
  const recurrenceUntil = form.recurrence_until ?? addCalendarDays(blockDate, 7)
  const occurrences = countOccurrences(blockDate, recurrenceUntil, form.recurrence)
  const validSeries = occurrences >= 1 && occurrences <= MAX_BLOCK_OCCURRENCES

  const handleSave = () => {
    // La hora tipeada es hora argentina (antes se mandaba como si fuera UTC).
    void editor.save({
      staffId,
      startsAt: argentinaLocalToUtcIso(blockDate, form.starts_at),
      endsAt: argentinaLocalToUtcIso(blockDate, form.ends_at),
      reason: form.reason,
      recurrence: form.recurrence,
      recurrenceUntil:
        form.recurrence === 'none'
          ? undefined
          : argentinaLocalToUtcIso(recurrenceUntil, form.ends_at),
      occurrences
    })
  }

  const handleReset = () => {
    if (editTarget) props.onDoneEditing()
    else setForm((prev) => initialForm(null, prev.staff_id))
  }

  return (
    <>
      <BlockForm
        form={form}
        blockDate={blockDate}
        recurrenceUntil={recurrenceUntil}
        staffId={staffId}
        staffMembers={staffMembers}
        templates={templatesQuery.data}
        isEditing={editTarget !== null}
        occurrences={occurrences}
        canSave={Boolean(staffId) && validSeries && !editor.saving && readOnlyReason === null}
        readOnlyReason={readOnlyReason}
        onChange={(patch) => setForm((prev) => ({ ...prev, ...patch }))}
        onSave={handleSave}
        onReset={handleReset}
      />
      {editor.pending && (
        <BlockPreviewModal
          preview={editor.pending.preview}
          reason={editor.pending.request.reason}
          busy={editor.busy}
          canCancel={props.canCancelAffected}
          onCancel={editor.dismiss}
          onConfirm={() => {
            void editor.confirm()
          }}
        />
      )}
    </>
  )
}
