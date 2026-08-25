import React, { useState } from 'react'

import {
  BellRing,
  CalendarCheck,
  CreditCard,
  FileText,
  LifeBuoy,
  Rocket,
  Scissors,
  Users
} from 'lucide-react'
import { Link } from 'react-router'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import { create2000sPanelStyle } from '../lib/surfaceStyles'

interface ManualStep {
  title: string
  body: string
  tip?: string
}

interface ManualSection {
  id: string
  icon: React.ReactNode
  title: string
  intro: string
  steps: ManualStep[]
}

const SECTIONS: ManualSection[] = [
  {
    id: 'primeros-pasos',
    icon: <Rocket className="w-4 h-4" />,
    title: 'Primeros pasos',
    intro:
      'El orden importa: sin servicios y personal cargados, tu página de reservas no puede mostrar turnos disponibles.',
    steps: [
      {
        title: '1. Completá los datos de tu negocio',
        body: 'En Configuración cargá el nombre, el logo y tu número de WhatsApp. Ese número es el que van a usar tus clientes para coordinar con vos.',
        tip: 'El "slug" es la dirección de tu página pública. Si tu slug es mibarberia, tus clientes reservan en /booking/mibarberia.'
      },
      {
        title: '2. Cargá tus servicios',
        body: 'En Servicios definí qué ofrecés, cuánto dura cada cosa y a qué precio. La duración es lo que determina cuántos turnos entran por día.',
        tip: 'Si un servicio lleva más tiempo del que pensás, es mejor cargarlo con la duración real: evita que se te superpongan turnos.'
      },
      {
        title: '3. Sumá a tu personal',
        body: 'En Personal agregá a cada persona que atiende y marcá qué servicios hace cada una.',
        tip: 'Si trabajás solo, cargate a vos mismo como personal. El sistema necesita saber quién atiende cada turno.'
      },
      {
        title: '4. Definí los horarios',
        body: 'A cada persona cargale sus días y horas de trabajo. Fuera de ese horario, nadie va a poder reservar.'
      }
    ]
  },
  {
    id: 'agenda',
    icon: <CalendarCheck className="w-4 h-4" />,
    title: 'Tu agenda día a día',
    intro:
      'La Agenda es la pantalla donde vas a pasar la mayor parte del tiempo. Cada turno pasa por estados y no todos los cambios son posibles.',
    steps: [
      {
        title: 'Los estados de un turno',
        body: 'Pendiente es una solicitud que todavía no confirmaste. Confirmado es un turno en firme. Completado es cuando ya atendiste. Ausente es cuando el cliente no vino. Cancelado y Vencido cierran el turno.'
      },
      {
        title: 'Los estados cerrados no se reabren',
        body: 'Una vez que marcaste un turno como completado, cancelado o ausente, no se puede volver atrás. Es a propósito: protege tu historial y tus reportes de cambios accidentales.',
        tip: 'Si te equivocaste, creá un turno nuevo en lugar de intentar revertir el anterior.'
      },
      {
        title: 'Bloquear horarios',
        body: 'Usá los bloqueos para vacaciones, un turno médico o cualquier rato en que no querés que te reserven. Un bloqueo le gana a cualquier reserva nueva en ese horario.'
      },
      {
        title: 'Liberar un turno con pago pendiente',
        body: 'Si alguien reservó y no pagó la seña, usá el botón Liberar. Primero vence el link de pago y después suelta el horario, así nadie puede pagar un turno que ya no existe.'
      }
    ]
  },
  {
    id: 'cobros',
    icon: <CreditCard className="w-4 h-4" />,
    title: 'Cobrar señas con Mercado Pago',
    intro:
      'La plata va directo de tu cliente a tu cuenta de Mercado Pago. Shifty nunca la toca ni la retiene.',
    steps: [
      {
        title: '1. Publicá tu política de seña',
        body: 'Antes de activar los cobros tenés que escribir tus condiciones: cuánto cobrás de seña, si se descuenta del total y en qué casos la devolvés. Sin esto el sistema no te deja activar los cobros.',
        tip: 'Sé concreto. Ese texto es lo que tu cliente acepta antes de pagar y es tu respaldo si después hay un reclamo.'
      },
      {
        title: '2. Conectá tu cuenta',
        body: 'En Configuración > Cobros online apretá "Conectar con Mercado Pago". Vas a ir a Mercado Pago, iniciás sesión con tu cuenta de siempre y autorizás. Listo.',
        tip: 'No tenés que copiar ninguna clave ni tocar nada técnico. Es un solo clic.'
      },
      {
        title: '3. Configurá la seña de cada servicio',
        body: 'En cada servicio elegís si la seña es opcional, obligatoria o si no cobrás seña. Podés definirla como un porcentaje o un monto fijo.'
      },
      {
        title: '4. Qué pasa cuando alguien reserva',
        body: 'Si paga la seña, el turno se confirma solo y te llega el aviso. Si elige coordinar por WhatsApp, el turno queda pendiente y lo confirmás vos cuando recibís la transferencia.'
      },
      {
        title: 'Si no pagan a tiempo',
        body: 'Un turno que espera la seña retiene el horario solo un rato. Si no se paga, se libera automáticamente y otra persona puede reservarlo.'
      },
      {
        title: 'Devoluciones',
        body: 'Podés devolver una seña ya cobrada desde Cobros online. Si el turno todavía estaba esperando el pago, se cancela. Si ya estaba confirmado, sigue confirmado: devolver la seña no cancela el turno por tu cuenta.'
      }
    ]
  },
  {
    id: 'avisos',
    icon: <BellRing className="w-4 h-4" />,
    title: 'Cómo te enterás de todo',
    intro: 'Hay dos canales, y conviene conocerlos para no perderte una reserva.',
    steps: [
      {
        title: 'La campanita del panel',
        body: 'Arriba a la derecha te muestra los turnos que esperan tu confirmación y las señas que se acreditaron. El número rojo son los avisos sin leer.'
      },
      {
        title: 'El correo',
        body: 'Los mismos avisos te llegan por mail a la dirección con la que entrás a Shifty, así te enterás aunque no tengas el panel abierto.'
      }
    ]
  },
  {
    id: 'clientes',
    icon: <Users className="w-4 h-4" />,
    title: 'Tus clientes',
    intro: 'Cada persona que reserva queda registrada con su historial.',
    steps: [
      {
        title: 'Autogestión',
        body: 'Tus clientes pueden ver, cancelar o reprogramar sus turnos desde tu página pública, validando su teléfono con un código.'
      },
      {
        title: 'La ventana de cancelación',
        body: 'En Configuración definís con cuántas horas de anticipación se puede cancelar. Pasado ese plazo, el cliente ya no puede hacerlo solo y tiene que hablar con vos.'
      },
      {
        title: 'Cuentas pendientes',
        body: 'Si trabajás con fiado, en Cuentas pendientes llevás el saldo de cada cliente con sus cargos y pagos.'
      }
    ]
  },
  {
    id: 'servicios',
    icon: <Scissors className="w-4 h-4" />,
    title: 'Promociones y reportes',
    intro: 'Dos herramientas para vender más y entender cómo te fue.',
    steps: [
      {
        title: 'Promociones',
        body: 'Creá códigos de descuento por porcentaje o monto fijo, con fecha de vencimiento y tope de usos. El cliente lo aplica al reservar.'
      },
      {
        title: 'Reportes',
        body: 'Ves tu facturación, los servicios más pedidos y tus mejores clientes. Podés descargar todo en Excel, CSV o PDF.'
      }
    ]
  }
]

const Manual: React.FC = () => {
  const [openSection, setOpenSection] = useState<string>(SECTIONS[0]?.id ?? '')

  return (
    <div className="space-y-6">
      <header className="rounded-[2rem] p-8" style={create2000sPanelStyle()}>
        <div className="flex items-start gap-4">
          <div
            className="p-3 rounded-2xl text-white"
            style={{
              background: `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
              border: `1px solid ${colors2000s.orange.accent}`,
              boxShadow: colors2000s.shadows.outerOrange
            }}
          >
            <LifeBuoy className="w-6 h-6" />
          </div>
          <div>
            <h1
              className="text-3xl font-black uppercase tracking-tight"
              style={{ color: colors2000s.orange.accent }}
            >
              Manual de uso
            </h1>
            <p
              className="text-sm font-bold mt-2 max-w-2xl"
              style={{ color: colors2000s.text.secondary }}
            >
              Todo lo que necesitás para poner tu negocio en marcha y manejarlo día a día.
              Si recién empezás, seguí las secciones en orden.
            </p>
          </div>
        </div>
      </header>

      <nav className="flex flex-wrap gap-2">
        {SECTIONS.map((section) => {
          const active = openSection === section.id
          return (
            <button
              key={section.id}
              type="button"
              onClick={() => setOpenSection(section.id)}
              className="px-4 py-2.5 rounded-xl text-[10px] font-black uppercase tracking-widest inline-flex items-center gap-2 transition-all active:scale-95 cursor-pointer"
              style={active ? buttonStyles2000s.selected : buttonStyles2000s.default}
            >
              {section.icon}
              {section.title}
            </button>
          )
        })}
      </nav>

      {SECTIONS.filter((section) => section.id === openSection).map((section) => (
        <section key={section.id} className="rounded-[2rem] p-8" style={create2000sPanelStyle()}>
          <h2
            className="text-lg font-black uppercase tracking-tight inline-flex items-center gap-2"
            style={{ color: colors2000s.orange.accent }}
          >
            {section.icon}
            {section.title}
          </h2>
          <p className="text-sm font-bold mt-2" style={{ color: colors2000s.text.secondary }}>
            {section.intro}
          </p>

          <div className="mt-6 space-y-4">
            {section.steps.map((step) => (
              <article
                key={step.title}
                className="rounded-2xl p-5"
                style={{
                  background: 'white',
                  border: `1px solid ${colors2000s.border.light}`,
                  boxShadow: colors2000s.shadows.insetDark
                }}
              >
                <h3
                  className="text-xs font-black uppercase tracking-widest"
                  style={{ color: colors2000s.text.primary }}
                >
                  {step.title}
                </h3>
                <p
                  className="text-sm leading-relaxed mt-2"
                  style={{ color: colors2000s.text.secondary }}
                >
                  {step.body}
                </p>
                {step.tip && (
                  <p
                    className="text-xs font-bold mt-3 pl-3"
                    style={{
                      color: colors2000s.orange.accent,
                      borderLeft: `3px solid ${colors2000s.orange.light}`
                    }}
                  >
                    {step.tip}
                  </p>
                )}
              </article>
            ))}
          </div>
        </section>
      ))}

      <footer
        className="rounded-[2rem] p-6 flex flex-wrap items-center justify-between gap-4"
        style={create2000sPanelStyle()}
      >
        <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
          ¿Buscás las condiciones del servicio?
        </p>
        <div className="flex flex-wrap gap-3">
          <Link
            to="/legal/terminos"
            target="_blank"
            className="px-4 py-2.5 rounded-xl text-[10px] font-black uppercase tracking-widest inline-flex items-center gap-2"
            style={buttonStyles2000s.default}
          >
            <FileText className="w-3.5 h-3.5" />
            Términos y condiciones
          </Link>
          <Link
            to="/legal/privacidad"
            target="_blank"
            className="px-4 py-2.5 rounded-xl text-[10px] font-black uppercase tracking-widest inline-flex items-center gap-2"
            style={buttonStyles2000s.default}
          >
            <FileText className="w-3.5 h-3.5" />
            Privacidad
          </Link>
        </div>
      </footer>
    </div>
  )
}

export default Manual
