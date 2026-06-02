import React, { useEffect, useMemo, useState } from "react";
import { format, addDays, subDays, startOfDay, addMinutes } from "date-fns";
import { Calendar as CalendarIcon, ChevronLeft, ChevronRight, Clock, Loader2, Plus, ShieldBan } from "lucide-react";

import { useAppointmentBlocks, useBlockTemplates, useCreateAppointmentBlock, useCreateRecurringAppointmentBlock, useDeleteAppointmentBlock, useUpdateAppointmentBlock } from "../hooks/useAppointmentBlocks";
import { useManagedStaff } from "../hooks/useManagedStaff";
import { useCalendarAppointments } from "../hooks/useCalendarAppointments";
import { buttonStyles2000s, colors2000s } from "../../theme/colors";

const TIME_SLOTS = Array.from({ length: 48 }, (_, i) => {
  const date = addMinutes(startOfDay(new Date()), (i + 16) * 15);
  return format(date, "HH:mm");
});

const toDateInput = (date: Date) => format(date, "yyyy-MM-dd");
const toTimeInput = (date: Date) => format(date, "HH:mm");

export const CalendarContainer: React.FC = () => {
  const [selectedDate, setSelectedDate] = useState(new Date());
  const [editingBlockId, setEditingBlockId] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [blockForm, setBlockForm] = useState({
    staff_id: "",
    date: toDateInput(new Date()),
    starts_at: "10:00",
    ends_at: "11:00",
    reason: "No atender",
    recurrence: "none" as "none" | "daily" | "weekly",
    recurrence_until: toDateInput(addDays(new Date(), 7)),
    max_occurrences: 5,
  });

  const dateStr = format(selectedDate, "yyyy-MM-dd");
  const { data: staffMembers, isLoading: loadingStaff } = useManagedStaff();
  const { data: appointments, isLoading: loadingAppts } = useCalendarAppointments(dateStr);
  const blocksQuery = useAppointmentBlocks();
  const templatesQuery = useBlockTemplates();
  const createBlock = useCreateAppointmentBlock();
  const createRecurringBlock = useCreateRecurringAppointmentBlock();
  const updateBlock = useUpdateAppointmentBlock();
  const deleteBlock = useDeleteAppointmentBlock();

  useEffect(() => {
    if (staffMembers?.length && !blockForm.staff_id) {
      setBlockForm((prev) => ({ ...prev, staff_id: staffMembers[0].id }));
    }
  }, [blockForm.staff_id, staffMembers]);

  useEffect(() => {
    setBlockForm((prev) => ({ ...prev, date: dateStr }));
  }, [dateStr]);

  const blocksForSelectedDate = useMemo(() => {
    return (blocksQuery.data || []).filter((block) => block.starts_at.slice(0, 10) === dateStr);
  }, [blocksQuery.data, dateStr]);

  const appointmentCards = useMemo(() => {
    return (appointments || []).map((app) => {
      const start = app.timeSpan.getStartsAt();
      const end = app.timeSpan.getEndsAt();
      const startMinutes = start.getUTCHours() * 60 + start.getUTCMinutes();
      const endMinutes = end.getUTCHours() * 60 + end.getUTCMinutes();
      const offsetMinutes = startMinutes - (4 * 60);
      const durationMinutes = Math.max(endMinutes - startMinutes, 30);
      return {
        id: app.id,
        staffId: app.staffId,
        serviceName: app.serviceName,
        clientName: app.clientName,
        top: `${Math.max(offsetMinutes / 15, 0) * 64}px`,
        height: `${Math.max((durationMinutes / 15) * 64, 64)}px`,
        timeLabel: format(start, "HH:mm"),
      };
    });
  }, [appointments]);

  const handleEditBlock = (block: { public_id: string; staff_id: string; starts_at: string; ends_at: string; reason: string }) => {
    const startsAt = new Date(block.starts_at);
    const endsAt = new Date(block.ends_at);
    setEditingBlockId(block.public_id);
    setBlockForm({
      staff_id: block.staff_id,
      date: toDateInput(startsAt),
      starts_at: toTimeInput(startsAt),
      ends_at: toTimeInput(endsAt),
      reason: block.reason,
      recurrence: "none",
      recurrence_until: toDateInput(addDays(startsAt, 7)),
      max_occurrences: 5,
    });
  };

  const handleResetBlockForm = () => {
    setEditingBlockId(null);
    setBlockForm((prev) => ({
      ...prev,
      date: dateStr,
      starts_at: "10:00",
      ends_at: "11:00",
      reason: "No atender",
      recurrence: "none",
      recurrence_until: toDateInput(addDays(selectedDate, 7)),
      max_occurrences: 5,
    }));
  };

  const handleSaveBlock = async () => {
    const startsAt = `${blockForm.date}T${blockForm.starts_at}:00Z`;
    const endsAt = `${blockForm.date}T${blockForm.ends_at}:00Z`;

    try {
      if (editingBlockId) {
        await updateBlock.mutateAsync({
          publicId: editingBlockId,
          payload: {
            staff_id: blockForm.staff_id,
            starts_at: startsAt,
            ends_at: endsAt,
            reason: blockForm.reason,
          },
        });
        setMessage("Bloqueo actualizado");
      } else if (blockForm.recurrence === "none") {
        await createBlock.mutateAsync({
          staff_id: blockForm.staff_id,
          starts_at: startsAt,
          ends_at: endsAt,
          reason: blockForm.reason,
        });
        setMessage("Bloqueo creado");
      } else {
        const recurrenceUntilTime = `${blockForm.recurrence_until}T${blockForm.ends_at}:00Z`;
        await createRecurringBlock.mutateAsync({
          staff_id: blockForm.staff_id,
          starts_at: startsAt,
          ends_at: endsAt,
          reason: blockForm.reason,
          recurrence: blockForm.recurrence,
          recurrence_until: recurrenceUntilTime,
          max_occurrences: blockForm.max_occurrences,
        });
        setMessage("Serie de bloqueos creada");
      }
      handleResetBlockForm();
    } catch (error: any) {
      setMessage(error.response?.data?.detail || "No se pudo guardar el bloqueo");
    }
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-700">
      <div className="flex flex-col md:flex-row items-center justify-between gap-6 p-6 rounded-3xl" style={{ background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`, border: `1px solid ${colors2000s.border.default}`, boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerMedium}` }}>
        <div className="flex items-center gap-4">
          <div className="w-12 h-12 rounded-2xl text-white flex items-center justify-center flex-shrink-0" style={{ background: `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`, border: `1px solid ${colors2000s.orange.accent}`, boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}` }}>
            <CalendarIcon size={24} />
          </div>
          <div>
            <h2 className="text-2xl font-black uppercase tracking-tight leading-none mb-1" style={{ color: colors2000s.text.primary }}>Agenda diaria</h2>
            <p className="text-[10px] font-black uppercase tracking-widest" style={{ color: colors2000s.text.secondary }}>Agenda operativa y bloqueos</p>
          </div>
        </div>

        <div className="flex items-center gap-3 p-2 rounded-2xl border" style={{ background: "white", borderColor: colors2000s.border.default, boxShadow: colors2000s.shadows.insetDark }}>
          <button onClick={() => setSelectedDate((prev) => subDays(prev, 1))} className="w-10 h-10 rounded-xl flex items-center justify-center transition-all active:scale-90" style={buttonStyles2000s.default}>
            <ChevronLeft size={20} className="text-gray-600" />
          </button>
          <div className="px-6 text-center min-w-[200px]">
            <p className="text-[9px] font-black uppercase tracking-widest mb-0.5" style={{ color: colors2000s.orange.accent }}>{format(selectedDate, "EEEE")}</p>
            <p className="text-base font-black uppercase tracking-tight" style={{ color: colors2000s.text.primary }}>{format(selectedDate, "dd 'de' MMMM")}</p>
          </div>
          <button onClick={() => setSelectedDate((prev) => addDays(prev, 1))} className="w-10 h-10 rounded-xl flex items-center justify-center transition-all active:scale-90" style={buttonStyles2000s.default}>
            <ChevronRight size={20} className="text-gray-600" />
          </button>
        </div>

        <div className="px-6 py-4 rounded-xl flex items-center gap-2 font-black uppercase tracking-widest text-xs" style={buttonStyles2000s.selected}>
          <Plus size={18} /> Nuevo turno
        </div>
      </div>

      {message && (
        <div className="p-4 rounded-2xl text-sm font-bold" style={{ background: "#fff7ed", border: "1px solid #fed7aa", color: "#c2410c" }}>
          {message}
        </div>
      )}

      <div className="rounded-[3rem] border overflow-hidden relative" style={{ background: "white", borderColor: colors2000s.border.default, boxShadow: colors2000s.shadows.outerMedium }}>
        {(loadingStaff || loadingAppts) && (
          <div className="absolute inset-0 z-50 bg-white/60 backdrop-blur-[2px] flex flex-col items-center justify-center">
            <Loader2 className="w-12 h-12 animate-spin text-orange-500 mb-4" />
            <p className="text-xs font-black text-gray-400 uppercase tracking-widest">Actualizando agenda...</p>
          </div>
        )}

        <div className="overflow-x-auto">
          <div className="min-w-[800px]">
            <div className="flex border-b" style={{ borderColor: colors2000s.border.light }}>
              <div className="w-20 flex-shrink-0 flex items-center justify-center border-r" style={{ borderColor: colors2000s.border.light }}>
                <Clock size={16} className="text-gray-400" />
              </div>
              <div className="flex flex-1" style={{ background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)` }}>
                {staffMembers?.map((staff, idx) => (
                  <div key={staff.id} className="flex-1 min-w-[150px] p-4 text-center border-r" style={{ borderColor: colors2000s.border.light }}>
                    <div className="w-10 h-10 rounded-full text-white flex items-center justify-center mx-auto mb-2 font-black text-xs shadow-md" style={{ background: idx % 2 === 0 ? "linear-gradient(180deg, #3b82f6 0%, #2563eb 100%)" : `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`, border: idx % 2 === 0 ? "1px solid #2563eb" : `1px solid ${colors2000s.orange.accent}`, boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}` }}>
                      {staff.displayName.split(" ").map((w) => w[0]).join("").toUpperCase()}
                    </div>
                    <p className="text-[10px] font-black uppercase tracking-tight text-gray-800">{staff.displayName}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="h-[600px] overflow-y-auto relative bg-white">
              <div className="flex">
                <div className="w-20 flex-shrink-0 bg-white sticky left-0 z-10 border-r" style={{ borderColor: colors2000s.border.light }}>
                  {TIME_SLOTS.map((time) => (
                    <div key={time} className="h-16 border-b border-gray-50 flex items-start justify-center pt-2">
                      <span className="text-[10px] font-black text-gray-400">{time}</span>
                    </div>
                  ))}
                </div>

                <div className="flex flex-1">
                  {staffMembers?.map((staff) => (
                    <div key={staff.id} className="flex-1 min-w-[150px] relative border-r border-gray-50">
                      {TIME_SLOTS.map((time) => (
                        <div key={time} className="h-16 border-b border-gray-50/50" />
                      ))}

                      {blocksForSelectedDate.filter((block) => block.staff_id === staff.id && block.is_active).map((block) => {
                        const start = new Date(block.starts_at);
                        const end = new Date(block.ends_at);
                        const startMinutes = start.getUTCHours() * 60 + start.getUTCMinutes();
                        const endMinutes = end.getUTCHours() * 60 + end.getUTCMinutes();
                        const offsetMinutes = startMinutes - (4 * 60);
                        return (
                          <button
                            key={block.public_id}
                            type="button"
                            onClick={() => handleEditBlock(block)}
                            className="absolute left-2 right-2 rounded-2xl p-3 border border-l-[5px] text-left"
                            style={{
                              top: `${Math.max(offsetMinutes / 15, 0) * 64}px`,
                              height: `${Math.max(((endMinutes - startMinutes) / 15) * 64, 64)}px`,
                              background: "linear-gradient(180deg, #fff7ed 0%, #fed7aa 100%)",
                              borderColor: "#fb923c",
                              borderLeftColor: "#c2410c",
                              boxShadow: "0 3px 6px rgba(0,0,0,0.05)",
                            }}
                          >
                            <p className="text-[8px] font-black uppercase tracking-widest text-orange-700 mb-1">{block.reason}</p>
                            <p className="text-[10px] font-black text-orange-900">{format(start, "HH:mm")} - {format(end, "HH:mm")}</p>
                          </button>
                        );
                      })}

                  {appointmentCards.filter((a) => a.staffId === staff.id).map((app) => (
                        <div
                          key={app.id}
                          className="absolute left-2 right-2 rounded-2xl p-3 border border-l-[5px] transition-all hover:scale-[1.02] active:scale-95 cursor-pointer flex flex-col justify-between"
                          style={{
                            top: app.top,
                            height: app.height,
                            background: "linear-gradient(180deg, #ffffff 0%, #f6f8f9 100%)",
                            borderColor: colors2000s.border.default,
                            borderLeftColor: colors2000s.orange.accent,
                            boxShadow: "inset 0 1px 0 rgba(255,255,255,0.8), 0 3px 6px rgba(0,0,0,0.05)",
                          }}
                        >
                          <div>
                            <p className="text-[8px] font-black uppercase tracking-widest text-orange-500 mb-0.5">{app.serviceName}</p>
                            <h4 className="text-[11px] font-black text-gray-800 uppercase truncate leading-tight">{app.clientName}</h4>
                          </div>
                          <span className="self-start px-2 py-0.5 rounded-lg text-[8px] font-black tracking-widest uppercase border" style={{ background: "white", borderColor: colors2000s.border.default, boxShadow: colors2000s.shadows.insetDark, color: colors2000s.text.secondary }}>
                            {app.timeLabel}
                          </span>
                        </div>
                      ))}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="grid xl:grid-cols-[1.05fr_0.95fr] gap-6">
        <div className="p-6 rounded-3xl space-y-4" style={{ background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`, border: `1px solid ${colors2000s.border.default}`, boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerMedium}` }}>
          <div className="flex items-center gap-3">
            <ShieldBan className="w-5 h-5" style={{ color: colors2000s.orange.accent }} />
            <h3 className="text-lg font-black uppercase tracking-tight" style={{ color: colors2000s.text.primary }}>Bloqueos de agenda</h3>
          </div>

          <div className="flex flex-wrap gap-2">
            {templatesQuery.data?.map((template) => (
              <button key={template.key} type="button" onClick={() => setBlockForm((prev) => ({ ...prev, reason: template.reason }))} className="px-3 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest" style={buttonStyles2000s.default}>
                {template.label}
              </button>
            ))}
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            <select value={blockForm.staff_id} onChange={(e) => setBlockForm((prev) => ({ ...prev, staff_id: e.target.value }))} className="rounded-2xl px-4 py-3 font-bold outline-none" style={{ background: "white", border: `1px solid ${colors2000s.border.default}`, boxShadow: colors2000s.shadows.insetDark, color: colors2000s.text.primary }}>
              {staffMembers?.map((staff) => (
                <option key={staff.id} value={staff.id}>{staff.displayName}</option>
              ))}
            </select>
            <input value={blockForm.reason} onChange={(e) => setBlockForm((prev) => ({ ...prev, reason: e.target.value }))} className="rounded-2xl px-4 py-3 font-bold outline-none" style={{ background: "white", border: `1px solid ${colors2000s.border.default}`, boxShadow: colors2000s.shadows.insetDark, color: colors2000s.text.primary }} placeholder="Motivo interno" />
          </div>

          <div className="grid md:grid-cols-3 gap-4">
            <input type="date" value={blockForm.date} onChange={(e) => setBlockForm((prev) => ({ ...prev, date: e.target.value }))} className="rounded-2xl px-4 py-3 font-bold outline-none" style={{ background: "white", border: `1px solid ${colors2000s.border.default}`, boxShadow: colors2000s.shadows.insetDark, color: colors2000s.text.primary }} />
            <input type="time" value={blockForm.starts_at} onChange={(e) => setBlockForm((prev) => ({ ...prev, starts_at: e.target.value }))} className="rounded-2xl px-4 py-3 font-bold outline-none" style={{ background: "white", border: `1px solid ${colors2000s.border.default}`, boxShadow: colors2000s.shadows.insetDark, color: colors2000s.text.primary }} />
            <input type="time" value={blockForm.ends_at} onChange={(e) => setBlockForm((prev) => ({ ...prev, ends_at: e.target.value }))} className="rounded-2xl px-4 py-3 font-bold outline-none" style={{ background: "white", border: `1px solid ${colors2000s.border.default}`, boxShadow: colors2000s.shadows.insetDark, color: colors2000s.text.primary }} />
          </div>

          {!editingBlockId && (
            <div className="grid md:grid-cols-3 gap-4">
              <select value={blockForm.recurrence} onChange={(e) => setBlockForm((prev) => ({ ...prev, recurrence: e.target.value as "none" | "daily" | "weekly" }))} className="rounded-2xl px-4 py-3 font-bold outline-none" style={{ background: "white", border: `1px solid ${colors2000s.border.default}`, boxShadow: colors2000s.shadows.insetDark, color: colors2000s.text.primary }}>
                <option value="none">Sin recurrencia</option>
                <option value="daily">Diaria</option>
                <option value="weekly">Semanal</option>
              </select>
              <input type="date" value={blockForm.recurrence_until} onChange={(e) => setBlockForm((prev) => ({ ...prev, recurrence_until: e.target.value }))} className="rounded-2xl px-4 py-3 font-bold outline-none" style={{ background: "white", border: `1px solid ${colors2000s.border.default}`, boxShadow: colors2000s.shadows.insetDark, color: colors2000s.text.primary }} />
              <input type="number" min={1} max={60} value={blockForm.max_occurrences} onChange={(e) => setBlockForm((prev) => ({ ...prev, max_occurrences: Number(e.target.value) || 1 }))} className="rounded-2xl px-4 py-3 font-bold outline-none" style={{ background: "white", border: `1px solid ${colors2000s.border.default}`, boxShadow: colors2000s.shadows.insetDark, color: colors2000s.text.primary }} />
            </div>
          )}

          <div className="flex flex-wrap gap-3">
            <button type="button" onClick={handleSaveBlock} disabled={!blockForm.staff_id} className="px-4 py-3 rounded-2xl text-xs font-black uppercase tracking-widest disabled:opacity-50" style={buttonStyles2000s.selected}>
              {editingBlockId ? "Actualizar bloqueo" : "Guardar bloqueo"}
            </button>
            <button type="button" onClick={handleResetBlockForm} className="px-4 py-3 rounded-2xl text-xs font-black uppercase tracking-widest" style={buttonStyles2000s.default}>
              Limpiar
            </button>
          </div>
        </div>

        <div className="p-6 rounded-3xl space-y-4" style={{ background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`, border: `1px solid ${colors2000s.border.default}`, boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerMedium}` }}>
          <h3 className="text-lg font-black uppercase tracking-tight" style={{ color: colors2000s.text.primary }}>Bloqueos del día</h3>
          <div className="space-y-3">
            {blocksForSelectedDate.map((block) => (
              <div key={block.public_id} className="rounded-2xl p-4 bg-white flex flex-col gap-3" style={{ border: `1px solid ${colors2000s.border.light}`, boxShadow: colors2000s.shadows.insetDark }}>
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-sm font-black" style={{ color: colors2000s.text.primary }}>{block.reason}</p>
                    <p className="text-[11px] font-bold" style={{ color: colors2000s.text.secondary }}>
                      {new Date(block.starts_at).toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit" })} - {new Date(block.ends_at).toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit" })}
                    </p>
                  </div>
                  <span className="px-2 py-1 rounded-xl text-[10px] font-black uppercase tracking-widest" style={{ background: block.is_active ? "#ffedd5" : "#e5e7eb", color: block.is_active ? "#c2410c" : "#6b7280" }}>
                    {block.is_active ? "Activo" : "Inactivo"}
                  </span>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={() => handleEditBlock(block)} className="px-3 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest" style={buttonStyles2000s.default}>
                    Editar
                  </button>
                  <button type="button" onClick={async () => {
                    try {
                      await deleteBlock.mutateAsync(block.public_id);
                      setMessage("Bloqueo desactivado");
                    } catch (error: any) {
                      setMessage(error.response?.data?.detail || "No se pudo desactivar");
                    }
                  }} className="px-3 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest" style={buttonStyles2000s.selected}>
                    Desactivar
                  </button>
                </div>
              </div>
            ))}
            {!blocksForSelectedDate.length && !blocksQuery.isLoading && (
              <div className="rounded-2xl p-6 bg-white text-sm font-bold" style={{ border: `1px solid ${colors2000s.border.light}`, boxShadow: colors2000s.shadows.insetDark, color: colors2000s.text.secondary }}>
                No hay bloqueos cargados para este día.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
