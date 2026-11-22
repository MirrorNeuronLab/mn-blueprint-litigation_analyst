"""Ask a completed Litigation Analyst case graph a read-only question."""

import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / 'payloads'))


def print_answer(result):
    print(result['summary'])
    for candidate in result.get('candidates', []):
        detail = f" ({candidate['detail']})" if candidate['detail'] else ''
        print(f"- {terminal_text(candidate['label'] + detail)} [{candidate['kind']}]")
    for edge in result.get('relationships', []):
        print(terminal_text(f"\n{edge['from_label']} — {edge['label']} → {edge['to_label']}\n{edge['qualification']}"))
        for passage in edge['passages']:
            print(terminal_text(f"  {passage['document']}, characters {passage['start_char']}–{passage['end_char']} "
                                f"[{passage['id']}]"))
    if result.get('truncated'):
        print('The answer reached its display limit. Narrow the question or inspect the case graph.')


def terminal_text(value):
    return re.sub(r'[\x00-\x09\x0b-\x1f\x7f-\x9f]', ' ', value)


def main():
    from domain.case_graph_query import open_graph, query

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run', type=Path, help='Completed run/archive containing review_index.json')
    parser.add_argument('question', nargs='?', help='Omit to ask questions interactively')
    parser.add_argument('--json', action='store_true', help='Emit one structured answer')
    args = parser.parse_args()
    if args.json and not args.question:
        parser.error('--json requires a question')
    try:
        with open_graph(args.run) as database:
            if args.question:
                result = query(database, args.question)
                if args.json:
                    print(json.dumps(result, ensure_ascii=False))
                else:
                    print_answer(result)
                return
            print('Ask the saved case graph. Press Ctrl-D to exit.')
            while True:
                try:
                    question = input('Case question: ').strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    return
                if question:
                    try:
                        print_answer(query(database, question))
                    except ValueError as error:
                        print(error)
    except (FileNotFoundError, ValueError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()
