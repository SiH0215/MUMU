"""Aggregate completed benchmark runs without publishing corpus audio or transcripts."""
import argparse
import json
from pathlib import Path

from experiments.benchmark_mumu import dump, stats


def llm_metrics(rows):
    good=[r for r in rows if 'error_type' not in r]
    return {variant:{
        'responses':len(items),
        'completion_seconds':stats([r['seconds'] for r in items]),
        'first_text_seconds':stats([r['first_text_seconds'] for r in items]),
        'characters':stats([r['characters'] for r in items]),
        'input_tokens':stats([r['usage']['input_tokens'] for r in items]),
        'output_tokens':stats([r['usage']['output_tokens'] for r in items]),
        'total_tokens':stats([r['usage']['total_tokens'] for r in items]),
        'question_responses':sum(r['questions']>0 for r in items),
        'questions':sum(r['questions'] for r in items),
        'within_session_fact_hits':sum(r.get('fact_hit',False) for r in items),
        'within_session_fact_tests':sum(bool(r.get('expected_fact')) for r in items),
        'sum_input_tokens':sum(r['usage']['input_tokens'] for r in items),
        'sum_output_tokens':sum(r['usage']['output_tokens'] for r in items),
        'completion_without_first_pair':stats([r['seconds'] for r in items if not(r['scenario']=='break' and r['turn']==1)]),
    } for variant in ('legacy','reverse') for items in [[r for r in good if r['variant']==variant]]}


def stt_metrics(rows):
    return {
        'n':len(rows),'reference_characters':sum(r['reference_characters'] for r in rows),
        'edits':sum(r['edits'] for r in rows),
        'cer':sum(r['edits'] for r in rows)/sum(r['reference_characters'] for r in rows),
        'exact_matches':sum(r['exact'] for r in rows),
        'question_samples':sum(r['question'] for r in rows),
        'missing_questions':sum(r['missing_question'] for r in rows),
        'inserted_questions':sum(r['inserted_question'] for r in rows),
        'processing_seconds':stats([r['seconds'] for r in rows]),
    }


def summary(folder):
    llm=json.loads((folder/'llm.json').read_text(encoding='utf-8'))
    stt=json.loads((folder/'stt.json').read_text(encoding='utf-8'))
    rag=json.loads((folder/'rag.json').read_text(encoding='utf-8'))
    assert len([r for r in llm['rows'] if 'error_type' not in r])==24
    assert len(stt['model_only'])==48 and len(stt['pipeline'])==56
    assert len(rag['positive'])==12 and len(rag['negative'])==6
    result={'llm':llm_metrics(llm['rows']),
            'llm_errors':[r['error_type'] for r in llm['rows'] if 'error_type' in r],
            'model_only':{m:stt_metrics([r for r in stt['model_only'] if r['model']==m]) for m in ('base','small')},
            'model_initial_load_seconds':stt['initial_load_seconds'],
            'pipeline':{},'rag':{}}
    for variant in ('legacy','reverse'):
        rows=[r for r in stt['pipeline'] if r['variant']==variant]
        speech=[r for r in rows if not r['non_speech']]
        result['pipeline'][variant]=stt_metrics(speech)
        result['pipeline'][variant]['short']=stt_metrics([r for r in speech if not r['over_five_seconds']])
        result['pipeline'][variant]['long']=stt_metrics([r for r in speech if r['over_five_seconds']])
        for group, subset in [('all',speech),('short',[r for r in speech if not r['over_five_seconds']]),('long',[r for r in speech if r['over_five_seconds']])]:
            result['pipeline'][variant]['first_submission_'+group]=stt_metrics([{**r,**r['first_submission']} for r in subset])
        result['pipeline'][variant]['non_speech_transcripts']=sum(bool(r['prediction']) for r in rows if r['non_speech'])
        result['pipeline'][variant]['non_speech_stt_calls']=sum(r['turns'] for r in rows if r['non_speech'])
        result['pipeline'][variant]['non_speech_total']=sum(r['non_speech'] for r in rows)
        result['pipeline'][variant]['submitted_audio_seconds']=sum(r['submitted_seconds'] for r in speech)
        result['pipeline'][variant]['split_speech_clips']=sum(r['turns']>1 for r in speech)
        result['pipeline'][variant]['missed_speech_clips']=sum(r['turns']==0 for r in speech)
        short=[r for r in speech if not r['over_five_seconds']]
        result['pipeline'][variant]['short_replay_estimate_seconds']=stats([r['capture_end_seconds']+r['seconds'] for r in short if r['capture_end_seconds'] is not None])
        if variant=='legacy':
            result['pipeline'][variant]['repeated_model_load_seconds']=stats([r['load_seconds'] for r in rows])
    result['rag']={
        'fixtures':rag['fixture_sessions'],
        'paraphrase_hits':sum(r['hit'] for r in rag['positive'] if r['style']=='paraphrase'),
        'same_text_hits':sum(r['hit'] for r in rag['positive'] if r['style']=='same_text'),
        'negative_matches':sum(r['results']>0 for r in rag['negative']),
        'search_seconds':stats([r['seconds'] for r in [*rag['positive'],*rag['negative']]]),
        'first_save_seconds':rag['save_seconds'][0],
        'warm_save_seconds':stats(rag['save_seconds'][1:]),
        'database_bytes':rag['database_bytes'],
        'generation':{v:{'n':len(rows),'fact_hits':sum(r.get('hit',False) for r in rows),
                          'errors':sum('error_type' in r for r in rows)}
                      for v in ('legacy','reverse') for rows in [[r for r in rag['generation'] if r['variant']==v]]},
    }
    result['stt_samples']=[{k:v for k,v in c.items() if k!='reference'} for c in stt['clips']]
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--quiet',action='store_true')
    args=parser.parse_args()
    result=summary(args.folder)
    dump(args.output,result)
    print('Wrote benchmark summary.' if args.quiet else json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
