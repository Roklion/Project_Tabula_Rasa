export function downloadBlob(content: Blob, filename: string) {
  const url = URL.createObjectURL(content);
  const link = document.createElement('a');
  link.href = url; link.download = filename;
  document.body.appendChild(link);
  try { link.click(); }
  finally {
    link.remove();
    // Let the browser initiate the download before releasing its URL.
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}
