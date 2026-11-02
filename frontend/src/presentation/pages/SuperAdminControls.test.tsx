import { fireEvent, render, screen } from '@testing-library/react'

import {
  superAdminPalette,
  superAdminPrimaryControlStyle,
  superAdminSelectedControlStyle
} from './superadmin/palette'
import { scopeBadgeStyle, statusBadgeStyle } from './superadmin/shared'
import { StoresSection } from './superadmin/StoresSection'
import { ActionButton, MiniButton } from './SuperAdminUi'
import { colors2000s } from '../../theme/colors'

describe('botones de accion del superadmin', () => {
  it('mantienen un objetivo de 44 px y un foco visible con contraste neutral', () => {
    render(
      <>
        <ActionButton label="Guardar" onClick={jest.fn()} />
        <MiniButton label="Ver" onClick={jest.fn()} />
      </>
    )

    for (const label of ['Guardar', 'Ver']) {
      expect(screen.getByRole('button', { name: label })).toHaveClass(
        'min-h-11',
        'focus-visible:outline-2',
        'focus-visible:outline-[var(--color-brand-accent)]'
      )
    }
  })

  it('usa el naranja claro del logo para controles y alcance, sin afectar estados semánticos', () => {
    expect(superAdminPalette.orangeLight).toBe('#ff8c42')
    expect(superAdminPalette.orangeDark).toBe('#e67e22')
    expect(superAdminPrimaryControlStyle.color).toBe('#ffffff')
    expect(superAdminPrimaryControlStyle).not.toHaveProperty('WebkitTextStroke')
    expect(superAdminPrimaryControlStyle).not.toHaveProperty('textShadow')
    expect(superAdminPrimaryControlStyle.background).toContain('#ff8c42')
    expect(superAdminPrimaryControlStyle.background).toContain('#e67e22')
    expect(superAdminSelectedControlStyle).toMatchObject(superAdminPrimaryControlStyle)
    expect(scopeBadgeStyle('global')).toMatchObject({
      color: '#ffffff',
      background: expect.stringContaining('#ff8c42')
    })
    expect(scopeBadgeStyle('tenant').color).toBe(colors2000s.text.primary)
    expect(statusBadgeStyle('success').background).toBe(colors2000s.status.success.bg)
    expect(statusBadgeStyle('danger').background).toBe(colors2000s.status.danger.bg)
  })
})

describe('filtros de tiendas del superadmin', () => {
  it('nombra los grupos y anuncia la opcion activa de cada filtro', () => {
    const setActivityFilter = jest.fn()
    const setSubscriptionFilter = jest.fn()

    render(
      <StoresSection
        search=""
        onSearchChange={jest.fn()}
        activityFilter="active"
        setActivityFilter={setActivityFilter}
        subscriptionFilter="with"
        setSubscriptionFilter={setSubscriptionFilter}
        selectedStoreId={null}
        setSelectedStoreId={jest.fn()}
        onViewStore={jest.fn()}
        storesQuery={{
          data: undefined,
          isLoading: true,
          isFetching: true,
          error: null,
          refetch: jest.fn(),
          total: null,
          hasNextPage: false,
          isFetchingNextPage: false,
          fetchNextPage: jest.fn()
        }}
        openEditStoreFor={jest.fn()}
        toggleStoreActive={jest.fn().mockResolvedValue(undefined)}
      />
    )

    const activityGroup = screen.getByRole('group', { name: 'Filtrar tiendas por estado' })
    const subscriptionGroup = screen.getByRole('group', {
      name: 'Filtrar tiendas por suscripción'
    })

    expect(screen.getByRole('button', { name: 'Activas', pressed: true })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Inactivas', pressed: false })).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Con suscripción', pressed: true })
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Sin suscripción', pressed: false })
    ).toBeInTheDocument()

    expect(activityGroup.contains(screen.getByRole('button', { name: 'Activas' }))).toBe(true)
    expect(
      subscriptionGroup.contains(screen.getByRole('button', { name: 'Con suscripción' }))
    ).toBe(true)

    for (const button of [
      ...activityGroup.querySelectorAll('button'),
      ...subscriptionGroup.querySelectorAll('button')
    ]) {
      expect(button).toHaveClass(
        'min-h-11',
        'focus-visible:outline-2',
        'focus-visible:outline-[var(--color-brand-accent)]'
      )
    }

    fireEvent.click(screen.getByRole('button', { name: 'Inactivas' }))
    fireEvent.click(screen.getByRole('button', { name: 'Sin suscripción' }))
    expect(setActivityFilter).toHaveBeenCalledWith('inactive')
    expect(setSubscriptionFilter).toHaveBeenCalledWith('without')
  })
})
