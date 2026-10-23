export const roleNames = { owner: 'Owner', admin: 'Admin', editor: 'Editor', accountant: 'Accountant', read_only: 'Read-only' };
export type Role = keyof typeof roleNames;
export const roleLabel = (role?: string | null) => role && role in roleNames ? roleNames[role as Role] : '';
