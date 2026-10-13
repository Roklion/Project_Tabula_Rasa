import { useForm } from 'react-hook-form';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { expect, it } from 'vitest';
import { SelectField, TextField } from './Fields';

it('preserves multiline drafts and associates both hints and field errors', async () => {
  function Draft() {
    const form = useForm({ defaultValues: { memo: '' } });
    return <><TextField form={form} name="memo" label="Memo" multiline hint="Optional notes for this record." />
      <button onClick={() => form.setError('memo', { message: 'Check this value.' })}>Flag memo</button></>;
  }
  render(<Draft />);
  const memo = screen.getByRole('textbox', { name: 'Memo' });
  await userEvent.type(memo, 'First line\nSecond line');
  await userEvent.click(screen.getByRole('button', { name: 'Flag memo' }));
  expect(memo.tagName).toBe('TEXTAREA');
  expect(memo).toHaveValue('First line\nSecond line');
  expect(memo).toHaveAttribute('aria-invalid', 'true');
  expect(memo).toHaveAccessibleDescription('Optional notes for this record. Check this value.');
});

it('shows full selected labels without changing native multiple-selection values', async () => {
  const longLabel = 'A very long historical tag name that remains readable when its native option is clipped';
  function Draft() {
    const form = useForm({ defaultValues: { tags: ['historical'] } });
    return <SelectField form={form} name="tags" label="Tags" multiple options={[
      { id: 'historical', name: longLabel }, { id: 'current', name: 'Current tag' },
    ]} />;
  }
  render(<Draft />);
  const tags = screen.getByRole('listbox', { name: 'Tags' });
  expect(tags).toHaveValue(['historical']);
  expect(screen.getByText('Selected: ' + longLabel)).toBeVisible();
  expect(tags).toHaveAccessibleDescription('Use Ctrl or Command to select more than one; use Shift to select a range. Selected: ' + longLabel);
  await userEvent.selectOptions(tags, 'current');
  expect(tags).toHaveValue(['historical', 'current']);
  expect(screen.getByText('Selected: ' + longLabel + '; Current tag')).toBeVisible();
});
