import React from 'react'

import { Link, useParams } from 'react-router'

import { colors2000s } from '../../theme/colors'

type LegalDocument = 'terminos' | 'privacidad'

interface LegalSection {
  title: string
  paragraphs: string[]
}

const TERMS_SECTIONS: LegalSection[] = [
  {
    title: '1. Qué es Shifty',
    paragraphs: [
      'Shifty es una plataforma de software que permite a comercios y profesionales independientes (en adelante, "la tienda") publicar su agenda y recibir reservas de turnos de sus propios clientes.',
      'Shifty provee únicamente la herramienta tecnológica. No presta el servicio que la tienda ofrece, no participa en su ejecución y no asume responsabilidad por su calidad, cumplimiento u oportunidad.'
    ]
  },
  {
    title: '2. Relación entre las partes',
    paragraphs: [
      'La relación de consumo por el servicio reservado se establece exclusivamente entre el cliente final y la tienda. Shifty no es parte de esa relación ni actúa como intermediario, mandatario o garante de ninguna de ellas.',
      'La tienda es la única responsable de la información que publica: precios, duración, disponibilidad, condiciones y política de seña.'
    ]
  },
  {
    title: '3. Pagos',
    paragraphs: [
      'Shifty no procesa, retiene ni administra fondos de los clientes finales. Cuando la tienda habilita el cobro de una seña, el pago se realiza directamente a la cuenta de Mercado Pago de la tienda, a través de la infraestructura de ese proveedor.',
      'Shifty no accede al dinero en ningún momento y no puede emitir, retener ni forzar reembolsos. Todo reclamo por un pago corresponde resolverlo entre el cliente final y la tienda, y en su caso ante el procesador de pagos.',
      'La tienda es responsable de cumplir sus obligaciones fiscales por los cobros que reciba.'
    ]
  },
  {
    title: '4. Señas, cancelaciones y reembolsos',
    paragraphs: [
      'Cada tienda define y publica su propia política de seña, cancelación y reembolso. Esa política se muestra al cliente antes de confirmar la reserva y es la que rige el vínculo entre ambos.',
      'Al reservar, el cliente declara haber leído y aceptado esa política. Shifty conserva el registro de esa aceptación con fecha y hora, a los efectos probatorios.',
      'Shifty no fija, valida ni audita las políticas de las tiendas, y no responde por su aplicación.'
    ]
  },
  {
    title: '5. Obligaciones de la tienda',
    paragraphs: [
      'La tienda se obliga a: publicar información veraz; honrar los turnos confirmados; mantener una política de seña clara y accesible; resolver por sí misma los reclamos de sus clientes; y cumplir la normativa aplicable, incluida la de defensa del consumidor y protección de datos personales.',
      'La tienda mantendrá indemne a Shifty frente a cualquier reclamo, denuncia, multa o daño derivado del servicio que presta, de la información que publica o del incumplimiento de sus obligaciones.'
    ]
  },
  {
    title: '6. Datos personales',
    paragraphs: [
      'Respecto de los datos de sus clientes, la tienda actúa como responsable del tratamiento y Shifty como encargado, tratándolos únicamente conforme a sus instrucciones y para prestar el servicio.',
      'El detalle de qué datos se tratan y con qué finalidad está descripto en la Política de Privacidad.'
    ]
  },
  {
    title: '7. Disponibilidad y limitación de responsabilidad',
    paragraphs: [
      'Shifty procura la continuidad del servicio pero no garantiza disponibilidad ininterrumpida ni ausencia de errores. Puede haber interrupciones por mantenimiento, fallas de terceros proveedores o causas de fuerza mayor.',
      'En la máxima medida permitida por la ley, la responsabilidad de Shifty se limita al monto abonado por la tienda por el servicio en los últimos tres meses, y no alcanza lucro cesante, pérdida de chance ni daños indirectos.'
    ]
  },
  {
    title: '8. Cambios y contacto',
    paragraphs: [
      'Shifty puede modificar estos términos. Los cambios relevantes se comunican por los canales habituales con antelación razonable.',
      'Para consultas sobre estos términos, escribinos por los canales de contacto informados por la plataforma.'
    ]
  }
]

const PRIVACY_SECTIONS: LegalSection[] = [
  {
    title: '1. Qué datos tratamos',
    paragraphs: [
      'De los clientes finales: nombre, teléfono, correo electrónico cuando lo aportan, y los datos de los turnos reservados. Si la tienda configuró campos adicionales, también las respuestas que el cliente complete.',
      'De las tiendas y su personal: datos de contacto, credenciales de acceso y la configuración de su cuenta.'
    ]
  },
  {
    title: '2. Para qué los usamos',
    paragraphs: [
      'Para gestionar las reservas, enviar confirmaciones y recordatorios, permitir a la tienda administrar su agenda y, cuando corresponde, iniciar el cobro de una seña.',
      'No vendemos datos personales ni los cedemos a terceros con fines publicitarios.'
    ]
  },
  {
    title: '3. Roles',
    paragraphs: [
      'La tienda es responsable del tratamiento de los datos de sus clientes. Shifty actúa como encargado y trata esos datos siguiendo sus instrucciones y para prestar el servicio contratado.'
    ]
  },
  {
    title: '4. Pagos y terceros',
    paragraphs: [
      'Cuando el cliente paga una seña, es redirigido a Mercado Pago. Los datos de la tarjeta o del medio de pago son tratados por ese proveedor bajo sus propias políticas: Shifty no los recibe ni los almacena.',
      'Utilizamos además proveedores de infraestructura y envío de correo, obligados contractualmente a la confidencialidad.'
    ]
  },
  {
    title: '5. Conservación y seguridad',
    paragraphs: [
      'Conservamos los datos mientras la cuenta esté activa y por los plazos legales aplicables. Aplicamos cifrado de credenciales sensibles, control de acceso por tienda y registro de auditoría.'
    ]
  },
  {
    title: '6. Derechos',
    paragraphs: [
      'El titular de los datos puede solicitar acceso, rectificación, actualización o supresión. El pedido puede canalizarse ante la tienda o ante Shifty, que lo derivará a quien corresponda.',
      'En Argentina, la Agencia de Acceso a la Información Pública es el órgano de control de la Ley 25.326 y atiende las denuncias por incumplimiento.'
    ]
  }
]

const DOCUMENTS: Record<LegalDocument, { title: string; intro: string; sections: LegalSection[] }> =
  {
    terminos: {
      title: 'Términos y Condiciones',
      intro:
        'Estas condiciones regulan el uso de Shifty por parte de las tiendas y de las personas que reservan turnos a través de la plataforma.',
      sections: TERMS_SECTIONS
    },
    privacidad: {
      title: 'Política de Privacidad',
      intro:
        'Describe qué datos personales tratamos, con qué finalidad y qué derechos tiene el titular de esos datos.',
      sections: PRIVACY_SECTIONS
    }
  }

const LegalPage: React.FC = () => {
  const { document: documentParam } = useParams<{ document: string }>()
  const key: LegalDocument = documentParam === 'privacidad' ? 'privacidad' : 'terminos'
  const doc = DOCUMENTS[key]

  return (
    <div
      className="min-h-screen font-sans py-10 px-4"
      style={{
        background: `linear-gradient(180deg, ${colors2000s.bg.primary} 0%, ${colors2000s.bg.secondary} 100%)`,
        color: colors2000s.text.primary
      }}
    >
      <div
        className="max-w-3xl mx-auto rounded-xl p-8"
        style={{
          background: 'white',
          border: `1px solid ${colors2000s.border.default}`,
          boxShadow: colors2000s.shadows.outerMedium
        }}
      >
        <h1
          className="text-2xl font-black tracking-tight mb-2 uppercase"
          style={{ color: colors2000s.orange.accent }}
        >
          {doc.title}
        </h1>
        <p className="text-sm mb-8" style={{ color: colors2000s.text.secondary }}>
          {doc.intro}
        </p>

        {doc.sections.map((section) => (
          <section key={section.title} className="mb-6">
            <h2
              className="text-sm font-black uppercase tracking-widest mb-2"
              style={{ color: colors2000s.text.primary }}
            >
              {section.title}
            </h2>
            {section.paragraphs.map((paragraph) => (
              <p
                key={paragraph.slice(0, 40)}
                className="text-sm leading-relaxed mb-2"
                style={{ color: colors2000s.text.secondary }}
              >
                {paragraph}
              </p>
            ))}
          </section>
        ))}

        <div
          className="mt-8 pt-6 flex flex-wrap gap-4"
          style={{ borderTop: `1px solid ${colors2000s.border.light}` }}
        >
          <Link
            to={key === 'terminos' ? '/legal/privacidad' : '/legal/terminos'}
            className="text-xs font-bold underline"
            style={{ color: colors2000s.orange.accent }}
          >
            {key === 'terminos' ? 'Ver Política de Privacidad' : 'Ver Términos y Condiciones'}
          </Link>
        </div>
      </div>
    </div>
  )
}

export default LegalPage
