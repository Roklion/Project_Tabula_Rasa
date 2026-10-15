import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { FilePicker } from './FilePicker';

describe('FilePicker', () => {
  it('passes chooser files unchanged and resets only when requested by the receipt owner', async () => {
    const onFiles = vi.fn();
    render(<FilePicker id="file" label="Receipt files" accept=".pdf" multiple resetAfterSelection onFiles={onFiles} />);
    const file = new File(['synthetic'], 'receipt.pdf', { type: 'application/pdf' });
    const input = screen.getByLabelText('Receipt files');
    await userEvent.upload(input, file);
    expect(onFiles).toHaveBeenCalledWith([file]);
    expect(input).toHaveValue('');
    await userEvent.upload(input, file);
    expect(onFiles).toHaveBeenCalledTimes(2);
  });
  it('rejects multiple files in a single-file zone and preserves a previous selection', async () => {
    const onFiles = vi.fn();
    render(<FilePicker id="file" label="CSV" accept=".csv" onFiles={onFiles} />);
    const input = screen.getByLabelText('CSV');
    const file = new File(['first'], 'first.csv', { type: 'text/csv' });
    await userEvent.upload(input, file);
    fireEvent.drop(input.parentElement!, { dataTransfer: { files: [file, new File(['second'], 'second.csv')] } });
    expect(screen.getByRole('alert')).toHaveTextContent('Choose one file at a time.');
    expect(onFiles).toHaveBeenCalledTimes(1);
    expect((input as HTMLInputElement).files?.[0]).toBe(file);
  });
  it('ignores drop events while its workflow fieldset is disabled', () => {
    const onFiles = vi.fn();
    render(<fieldset disabled><FilePicker id="file" label="CSV" accept=".csv" onFiles={onFiles} /></fieldset>);
    fireEvent.drop(screen.getByLabelText('CSV').parentElement!, { dataTransfer: { files: [new File(['synthetic'], 'file.csv')] } });
    expect(onFiles).not.toHaveBeenCalled();
  });
});
