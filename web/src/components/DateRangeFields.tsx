import { Field } from './States';

/** Native inclusive-date controls; each caller owns filtering and date scope. */
export function DateRangeFields({ prefix, start = '', end = '', endLabel = 'To', onStart, onEnd }: {
  prefix: string; start?: string; end?: string; endLabel?: string; onStart: (value: string) => void; onEnd: (value: string) => void;
}) {
  return <><Field id={prefix + '-from'} label="From"><input id={prefix + '-from'} type="date" value={start} onChange={event => onStart(event.target.value)} /></Field>
    <Field id={prefix + '-to'} label={endLabel}><input id={prefix + '-to'} type="date" value={end} onChange={event => onEnd(event.target.value)} /></Field></>;
}
