import React from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useUsers } from './useUsers';
import { ServiceContainer } from '../../infrastructure/di/ServiceContainer';

// Mock de dependencias
const mockUserService = {
  listUsers: jest.fn(),
  createUser: jest.fn(),
  updateUser: jest.fn(),
  deleteUser: jest.fn(),
};

describe('useUsers hook factory', () => {
  let queryClient: QueryClient;
  let wrapper: React.FC<{ children: React.ReactNode }>;

  beforeAll(() => {
    // Configurar ServiceContainer con el mock
    const container = ServiceContainer.getInstance();
    container.clear();
    container.register('userService', () => mockUserService);
  });

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    wrapper = ({ children }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    jest.clearAllMocks();
  });

  it('should resolve service and fetch users on mount', async () => {
    const mockUsers = [{ id: '1', email: 'test@shifty.com' }];
    mockUserService.listUsers.mockResolvedValue(mockUsers);

    const { result } = renderHook(() => useUsers(), { wrapper });

    expect(result.current.getAllUsersQuery.isLoading).toBe(true);

    await waitFor(() => expect(result.current.getAllUsersQuery.isSuccess).toBe(true));

    expect(result.current.getAllUsersQuery.data).toEqual(mockUsers);
    expect(mockUserService.listUsers).toHaveBeenCalledTimes(1);
  });

  it('should trigger createUser mutation successfully', async () => {
    const newUser = { id: '2', email: 'new@shifty.com' };
    mockUserService.createUser.mockResolvedValue(newUser);

    const { result } = renderHook(() => useUsers(), { wrapper });

    result.current.createUserMutation.mutate({
      email: 'new@shifty.com',
      firstName: 'New',
      lastName: 'User',
      phone: '1234',
      role: 'staff',
      password: 'password',
    });

    await waitFor(() => expect(result.current.createUserMutation.isSuccess).toBe(true));

    expect(result.current.createUserMutation.data).toEqual(newUser);
  });
});
