"""Compare native full-clip STT and actual 5-second/VAD pipelines on local KsponSpeech.

No microphone is opened. Dataset audio/transcripts remain in the local output directory.
"""
import argparse
import ast
import gc
import hashlib
import json
from pathlib import Path, PurePosixPath
from random import Random
import re
from time import perf_counter
from types import SimpleNamespace
import warnings
from zipfile import ZipFile

import numpy as np
import torch

from experiments.benchmark_mumu import dump
from experiments.evaluate_stt import edit_distance, ends_with_question_mark, normalize, replay
from mumu.voice import load_transcriber, load_vad, transcribe, waveform


def samples(folder):
    scripts, = folder.rglob('KsponSpeech_scripts.zip')
    audio, = folder.rglob('KsponSpeech_eval.zip')
    with ZipFile(scripts) as labels, ZipFile(audio) as sounds:
        entries = {PurePosixPath(e.filename).name:e for e in sounds.infolist() if e.filename.startswith('eval_clean/') and e.filename.endswith('.pcm')}
        bins = {(punct,length):[] for punct in ('?','.') for length in ('short','long')}
        for line in labels.read('eval_clean.trn').decode('utf-8-sig').splitlines():
            source, reference = line.split(' :: ',1)
            reference=reference.strip()
            if not re.fullmatch(r'[가-힣A-Za-z0-9 ,]+[.?]',reference):
                continue
            entry=entries[PurePosixPath(source).name]
            seconds=(entry.file_size//2)/16000
            length='short' if 1.5<=seconds<=4.5 else ('long' if 5.5<=seconds<=9 else None)
            if length:
                bins[(reference[-1],length)].append((entry.filename,reference,seconds))
        chosen=[]
        rng=Random(20261120)
        for key in bins:
            chosen.extend(rng.sample(sorted(bins[key]),8 if key[1]=='short' else 4))
        rng.shuffle(chosen)
        for name,reference,seconds in chosen:
            raw=sounds.read(name)
            pcm=raw[:len(raw)//2*2]
            yield {'id':name,'reference':reference,'seconds':seconds,'trailing_bytes_removed':len(raw)-len(pcm),
                   'sha256':hashlib.sha256(pcm).hexdigest(),'pcm':pcm}


def metrics(reference, prediction):
    ref,hyp=normalize(reference),normalize(prediction)
    return {'edits':edit_distance(ref,hyp),'reference_characters':len(ref),'exact':ref==hyp,
            'question':ends_with_question_mark(reference),
            'missing_question':ends_with_question_mark(reference) and not ends_with_question_mark(prediction),
            'inserted_question':not ends_with_question_mark(reference) and ends_with_question_mark(prediction)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset',type=Path,required=True)
    parser.add_argument('--legacy',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    output=args.output/'stt.json'
    if output.exists():
        raise RuntimeError('Output exists. Use a fresh directory.')
    warnings.filterwarnings('ignore',message='FP16 is not supported on CPU')
    torch.set_num_threads(4)
    assert not torch.cuda.is_available(), 'This benchmark is designed for the shared CPU path.'
    clips=list(samples(args.dataset))
    print(f'Selected {len(clips)} KsponSpeech eval_clean clips: 16 short, 8 long, 12 questions, 12 statements',flush=True)
    report={'seed':20261120,'threads':4,'device':'cpu','source':'KsponSpeech eval_clean',
            'model_only':[],'pipeline':[],'fixed_window_seconds':int(16000/1024*5)*1024/16000,
            'clips':[{k:v for k,v in c.items() if k!='pcm'} for c in clips]}
    load_times={}
    models={}
    for name in ('base','small'):
        started=perf_counter()
        models[name]=load_transcriber(name)
        load_times[name]=perf_counter()-started
        # One common warm-up; never include initialization in pure inference times.
        if name=='base':
            models[name].transcribe(np.zeros(16000,dtype=np.float32),language='ko')
        else:
            transcribe(models[name],bytes(32000))
    report['initial_load_seconds']=load_times
    for index,clip in enumerate(clips):
        order=('base','small') if index%2==0 else ('small','base')
        for name in order:
            started=perf_counter()
            if name=='base':
                prediction=models[name].transcribe(waveform(clip['pcm']),language='ko')['text'].strip()
            else:
                prediction=transcribe(models[name],clip['pcm'])
            seconds=perf_counter()-started
            report['model_only'].append({'id':clip['id'],'model':name,'seconds':seconds,'audio_seconds':clip['seconds'],
                                         'prediction':prediction,**metrics(clip['reference'],prediction)})
        dump(output,report)
        print(f'MODEL {index+1}/{len(clips)}',flush=True)
    del models['base']
    gc.collect()
    # Execute the original stt() body, replacing only the microphone source and cache location.
    source=args.legacy/'pages/chat.py'
    tree=ast.parse(source.read_text(encoding='utf-8-sig'))
    stt,= [n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='stt']
    namespace={'st':SimpleNamespace(session_state={})}
    exec(compile(ast.Module(body=[stt],type_ignores=[]),str(source),'exec'),namespace)
    vad=load_vad()
    rng=np.random.default_rng(20261120)
    negatives=[('silence-5s',bytes(160000)),('silence-12s',bytes(384000)),
               ('white-noise-quiet',(rng.normal(0,.005,80000).clip(-1,1)*32767).astype('<i2').tobytes()),
               ('white-noise-loud',(rng.normal(0,.02,80000).clip(-1,1)*32767).astype('<i2').tobytes())]
    pipeline_clips=[*clips,*[{'id':n,'reference':'','seconds':len(p)/32000,'pcm':p} for n,p in negatives]]
    limit=int(16000/1024*5)*1024*2
    for index,clip in enumerate(pipeline_clips):
        for variant in (('legacy','reverse') if index%2==0 else ('reverse','legacy')):
            if variant=='legacy':
                load=[]
                def loader(name):
                    started=perf_counter()
                    model=load_transcriber(name)
                    load.append(perf_counter()-started)
                    return model
                namespace['whisper']=SimpleNamespace(load_model=loader)
                namespace['record_audio']=lambda status=None:waveform(clip['pcm'][:limit].ljust(limit,b'\0'))
                started=perf_counter()
                prediction=namespace['stt']().strip()
                elapsed=perf_counter()-started
                row={'id':clip['id'],'variant':variant,'seconds':elapsed,'load_seconds':sum(load),
                     'inference_seconds':elapsed-sum(load),'turns':1,'submitted_seconds':limit/32000,
                     'capture_end_seconds':limit/32000}
            else:
                started=perf_counter()
                turns=list(replay(clip['pcm']+bytes(32000),vad,800))
                vad_seconds=perf_counter()-started
                started=perf_counter()
                texts=[transcribe(models['small'],t.pcm) for t in turns]
                prediction=' '.join(texts).strip()
                inference_seconds=perf_counter()-started
                row={'id':clip['id'],'variant':variant,'seconds':vad_seconds+inference_seconds,
                     'vad_seconds':vad_seconds,'inference_seconds':inference_seconds,'turns':len(turns),
                     'submitted_seconds':sum(len(t.pcm) for t in turns)/32000,
                     'capture_end_seconds':turns[-1].end_ms/1000 if turns else None}
            row.update({'prediction':prediction,'non_speech':not bool(clip['reference']),
                        'over_five_seconds':clip['seconds']>limit/32000,
                        **metrics(clip['reference'],prediction)})
            first=prediction if variant=='legacy' else (texts[0] if texts else '')
            row['first_submission']=metrics(clip['reference'],first)
            report['pipeline'].append(row)
            dump(output,report)
            print(f'PIPELINE {index+1}/{len(pipeline_clips)} {variant}: {row["seconds"]:.2f}s turns={row["turns"]}',flush=True)
    dump(output,report)
    print('STT benchmark complete.',flush=True)


if __name__=='__main__':
    main()
