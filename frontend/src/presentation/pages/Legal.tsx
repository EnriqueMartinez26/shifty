import React from 'react'

import { Link, useParams } from 'react-router'

import { getContactInfo, type ContactInfo } from '@shared/utils/contactInfo'

import { colors2000s } from '../../theme/colors'
import { LegalLayout } from '../components/organisms/LegalLayout'
import { NotFoundScreen } from '../components/organisms/NotFoundScreen'
import { useDocumentTitle } from '../hooks/useDocumentTitle'

type LegalDocument = 'terminos' | 'privacidad'

interface LegalSection {
  title: string
  paragraphs: string[]
}

// Sin email configurado queda el texto generico; con uno, el email (Res.
// 104/2005: telefono o email de contacto).
const GENERIC_TERMS_CONTACT =
  'Para consultas sobre estos términos, escribinos por los canales de contacto informados por la plataforma.'

const contactParagraph = (paragraph: string, email: string | null): string =>
  paragraph === GENERIC_TERMS_CONTACT && email
    ? `Para consultas sobre estos términos, escribinos a ${email}.`
    : paragraph

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
      'Para los datos que se tratan al gestionar una reserva, la tienda actúa como responsable y Shifty como encargado según sus instrucciones. La analítica opcional de uso de la plataforma es una finalidad separada, detallada en la Política de Privacidad.',
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
      GENERIC_TERMS_CONTACT
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
      'Los datos operativos de agenda no se usan en otra tienda. La analítica opcional de GA4 es una finalidad separada que mide el uso del portal después de que la persona acepta; su alcance publicitario y los demás destinos requieren confirmación antes de publicar este aviso.'
    ]
  },
  {
    title: '3. Roles',
    paragraphs: [
      'Para los datos necesarios para gestionar una reserva, la tienda es responsable y Shifty actúa como encargado según sus instrucciones. La analítica opcional de uso del portal es una finalidad separada definida por Shifty; el rol legal de Shifty y Google para esos eventos y su base jurídica requieren confirmación profesional.'
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
    title: '5. Analítica opcional en el portal de reservas',
    paragraphs: [
      'Google Analytics (GA4) se carga solo después de que aceptás la opción de analítica desde el portal de reserva. La recopilación se activa solo en esas páginas mientras la aceptación siga vigente; al salir del portal o retirar la aceptación, la medición se bloquea. Si el script ya se descargó, puede permanecer en la página hasta que la recargues. GA4 puede generar eventos técnicos como `first_visit` y `session_start` según la primera visita o la sesión; ambos se observaron en la prueba controlada del 11/10/2026.',
      'La página informada es fija y no incluye el slug, query, fragmento ni la página de origen. La integración no agrega respuestas del formulario, códigos de verificación ni identificadores de turnos, tiendas, servicios o profesionales.',
      'El código deniega `ad_storage`, `ad_user_data` y `ad_personalization`, desactiva Google Signals y las señales de personalización, y no envía el `page_view` inicial. En la propiedad revisada el 11/10/2026, Medición mejorada y Google Signals están desactivados, pero la personalización publicitaria se permite en 307/307 regiones; no hay vínculo con Google Ads. La entidad y región de tratamiento, los roles y la base jurídica requieren confirmación profesional antes de publicar.',
      'La propiedad tiene retención configurada de 2 meses para eventos y 14 meses para datos de usuario. Las cookies de esta integración vencen a los 30 días configurados en el código. La región efectiva de procesamiento y otras vinculaciones de productos siguen sin confirmar.',
      'Podés rechazar la analítica y reservar igual, o retirar la preferencia desde "Preferencias de analítica". Esto detiene nuevos envíos y elimina las cookies de esta integración que sean accesibles en este navegador; no borra datos que Google ya recibió. La elección se guarda en este navegador hasta que la cambies o borres los datos del sitio.'
    ]
  },
  {
    title: '6. Conservación y seguridad',
    paragraphs: [
      'Conservamos los datos mientras la cuenta esté activa y por los plazos legales aplicables. Aplicamos cifrado de credenciales sensibles, control de acceso por tienda y registro de auditoría.'
    ]
  },
  {
    title: '7. Derechos',
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

const contactLineStyle = { color: colors2000s.text.primary }
const contactLinkStyle = { color: colors2000s.orange.accent }

/**
 * Identidad y contacto del responsable (Ley 25.326, art. 6) desde la
 * configuracion del build: el repo es publico y los datos reales no van al
 * codigo. Cada linea aparece solo si su dato es valido; sin ninguno, no hay
 * bloque. Domicilio y CUIT quedan afuera a proposito por ahora.
 */
const LegalContactBlock: React.FC<{ contact: ContactInfo }> = ({ contact }) => {
  const { responsables, email, whatsAppNumber } = contact
  if (!responsables && !email && !whatsAppNumber) return null
  return (
    <section aria-labelledby="legal-contacto" className="mb-8">
      <h2
        id="legal-contacto"
        className="text-base font-black uppercase tracking-widest mb-3"
        style={{ color: colors2000s.text.primary }}
      >
        Responsables y contacto
      </h2>
      <ul className="text-base leading-7 space-y-1">
        {responsables && <li style={contactLineStyle}>Responsables: {responsables}</li>}
        {email && (
          <li style={contactLineStyle}>
            Email:{' '}
            <a href={`mailto:${email}`} className="font-bold underline" style={contactLinkStyle}>
              {email}
            </a>
          </li>
        )}
        {whatsAppNumber && (
          <li style={contactLineStyle}>
            WhatsApp:{' '}
            <a
              href={`https://wa.me/${whatsAppNumber}`}
              target="_blank"
              rel="noreferrer"
              className="font-bold underline"
              style={contactLinkStyle}
            >
              +{whatsAppNumber}
            </a>
          </li>
        )}
      </ul>
    </section>
  )
}

const isLegalDocument = (value: string | undefined): value is LegalDocument =>
  value === 'terminos' || value === 'privacidad'

const LegalPage: React.FC = () => {
  const { document: documentParam } = useParams<{ document: string }>()
  // Un documento invalido no fija titulo: lo pone el 404 de abajo.
  useDocumentTitle(
    isLegalDocument(documentParam) ? `${DOCUMENTS[documentParam].title} · Shifty` : null
  )
  // Un documento que no existe (p. ej. /legal/cookies) es un 404, no los
  // terminos con otra direccion.
  if (!isLegalDocument(documentParam)) return <NotFoundScreen />

  const key = documentParam
  const doc = DOCUMENTS[key]
  const contact = getContactInfo()

  return (
    <LegalLayout title={doc.title} intro={doc.intro}>
      {doc.sections.map((section) => (
        <section key={section.title} className="mb-8">
          <h2
            className="text-base font-black uppercase tracking-widest mb-3"
            style={{ color: colors2000s.text.primary }}
          >
            {section.title}
          </h2>
          {section.paragraphs.map((paragraph) => (
            <p
              key={paragraph.slice(0, 40)}
              className="text-base leading-7 mb-3"
              style={{ color: colors2000s.text.primary }}
            >
              {contactParagraph(paragraph, contact.email)}
            </p>
          ))}
        </section>
      ))}

      <LegalContactBlock contact={contact} />

      <div
        className="mt-10 pt-6 flex flex-wrap gap-4"
        style={{ borderTop: `1px solid ${colors2000s.border.light}` }}
      >
        <Link
          to={key === 'terminos' ? '/legal/privacidad' : '/legal/terminos'}
          className="text-sm font-bold underline"
          style={{ color: colors2000s.orange.accent }}
        >
          {key === 'terminos' ? 'Ver Política de Privacidad' : 'Ver Términos y Condiciones'}
        </Link>
      </div>
    </LegalLayout>
  )
}

export default LegalPage
