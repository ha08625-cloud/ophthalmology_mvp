python3 -c "
import json

# Count unique outputs
outputs = {}
with open('training_data.jsonl', 'r') as f:
    for line in f:
        data = json.loads(line)
        output = data['output']
        outputs[output] = outputs.get(output, 0) + 1

# Sort by frequency
sorted_outputs = sorted(outputs.items(), key=lambda x: x[1], reverse=True)

print('Top 20 most common outputs:')
print('Count | Output')
print('-' * 60)
for output, count in sorted_outputs[:20]:
    # Truncate long outputs
    display = output if len(output) < 80 else output[:77] + '...'
    print(f'{count:3d}   | {display}')

print()
print(f'Total unique outputs: {len(outputs)}')
print(f'Total examples: {sum(outputs.values())}')
"