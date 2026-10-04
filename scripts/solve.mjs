import {solve} from '../src/core.mjs';
process.stdin.setEncoding('utf8');let data='';for await(const chunk of process.stdin)data+=chunk;
try{const input=JSON.parse(data);const output=Array.isArray(input)?input.map(x=>solve(x,{maxMs:30000})):solve(input,{maxMs:30000});process.stdout.write(JSON.stringify(output));}catch(e){process.stderr.write(e.message+'\n');process.exitCode=1;}
