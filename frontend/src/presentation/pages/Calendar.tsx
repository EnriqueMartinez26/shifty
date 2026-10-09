import React from 'react'

import { CalendarContainer } from '@presentation/containers/CalendarContainer'

import { useDocumentTitle } from '../hooks/useDocumentTitle'

const CalendarPage: React.FC = () => {
  useDocumentTitle('Agenda · Shifty')
  return (
    <div className="duration-700">
      <CalendarContainer />
    </div>
  )
}

export default CalendarPage
