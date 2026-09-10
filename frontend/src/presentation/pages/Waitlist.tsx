import React from 'react'

import { WaitlistContainer } from '@presentation/containers/WaitlistContainer'

const WaitlistPage: React.FC = () => {
  return (
    <div className="animate-in fade-in slide-in-from-bottom-4 duration-700">
      <WaitlistContainer />
    </div>
  )
}

export default WaitlistPage
