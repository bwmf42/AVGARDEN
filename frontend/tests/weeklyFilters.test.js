import test from 'node:test'
import assert from 'node:assert/strict'
import {filterWeekly,durationMinutes,releaseDay} from '../src/utils/weeklyFilters.js'
const items = [
 {id:'A-001',actresses:['Actor A'],genres:['Drama','Studio'],duration:'120分',releaseDate:'2026/9/1',hasChinese:true,downloaded:true},
 {id:'A-002',actresses:['Actor B'],genres:['Drama'],duration:'60',releaseDate:'2026-08-02'},
 {id:'A-003',actresses:['Actor A'],genres:['Studio']},
 {id:'A-004',actresses:['Actor C'],genres:[],duration:'180分钟',queueStatus:'queued'}
]
const states={'A-001':{watched_at:'2026-09-02',interest:'want'},'A-002':{watched_at:'2026-09-01',interest:'dismissed'}}
const ids = (query) => filterWeekly(items,query,states,['Actor A']).map(v=>v.id)
test('legacy browsing and user decisions stay distinct',()=>{
 assert.deepEqual(ids({}),['A-003','A-004'])
 assert.deepEqual(ids({tab:'want'}),['A-001'])
 assert.deepEqual(ids({tab:'dismissed'}),['A-002'])
 assert.deepEqual(ids({tab:'watched'}),['A-001'])
 assert.deepEqual(ids({tab:'all'}),['A-001','A-003','A-004'])
})
test('combined filters use all included and any excluded tags',()=>{
 assert.deepEqual(ids({tab:'all',fav:'1',include:'Drama,Studio',chinese:'yes',availability:'local',duration:'medium',from:'2026-09-01'}),['A-001'])
 assert.deepEqual(ids({tab:'all',include:'Studio',exclude:'Drama'}),['A-003'])
 assert.deepEqual(ids({tab:'all',actor:'Actor A',duration:'unknown'}),['A-003'])
 assert.deepEqual(ids({tab:'all',availability:'queued'}),['A-004'])
 assert.deepEqual(filterWeekly([{...items[0],hasFavoriteActress:true}],{tab:'all',fav:'1'},states,[]),[])
})
test('missing metadata never passes numeric/date bounds',()=>{
 assert.deepEqual(ids({tab:'all',from:'2026-09-02'}),[])
 assert.deepEqual(ids({tab:'all',duration:'short'}),[])
 assert.deepEqual(ids({tab:'all',dateUnknown:'1'}),['A-003','A-004'])
 assert.equal(releaseDay('2026-02-30'),'')
 assert.equal(durationMinutes('未知'),null)
 assert.equal(durationMinutes('2小时30分'),150)
 assert.equal(durationMinutes('02:00:00'),120)
})
