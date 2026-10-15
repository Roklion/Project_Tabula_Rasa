import { useRef, useState } from 'react';

/** File selection only. Callers own validation, preparation and explicit writes. */
export function FilePicker({ id, label, accept, multiple = false, disabled = false, resetAfterSelection = false, onFiles }: {
  id: string; label: string; accept: string; multiple?: boolean; disabled?: boolean;
  resetAfterSelection?: boolean; onFiles: (files: File[]) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState('');
  function select(files: FileList | null) {
    if (input.current?.matches(':disabled')) return;
    if (!multiple && (files?.length ?? 0) > 1) { setError('Choose one file at a time.'); return; }
    setError('');
    onFiles(Array.from(files ?? []));
    if (resetAfterSelection && input.current) input.current.value = '';
  }
  return <div className="field">
    <label htmlFor={id}>{label}</label>
    <div className="fileDropZone" onDragOver={event => { event.preventDefault(); }} onDrop={event => {
      event.preventDefault();
      if (!input.current || input.current.matches(':disabled') || !event.dataTransfer.files.length) return;
      if (!multiple && event.dataTransfer.files.length > 1) { setError('Choose one file at a time.'); return; }
      input.current.files = event.dataTransfer.files;
      select(event.dataTransfer.files);
    }}>
      <p id={id + '-help'} className="fieldHint">{multiple ? 'Drop files here or choose files.' : 'Drop a file here or choose a file.'}</p>
      <input ref={input} id={id} type="file" accept={accept} multiple={multiple} disabled={disabled}
        aria-describedby={id + '-help' + (error ? ' ' + id + '-error' : '')}
        onChange={event => select(event.target.files)} />
    </div>
    {error && <p id={id + '-error'} role="alert">{error}</p>}
  </div>;
}
