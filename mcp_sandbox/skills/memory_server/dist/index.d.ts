#!/usr/bin/env node
export declare const defaultMemoryPath: string;
export declare function ensureMemoryFilePath(): Promise<string>;
export interface Entity {
    name: string;
    entityType: string;
    observations: string[];
}
export interface Relation {
    from: string;
    to: string;
    relationType: string;
}
export interface KnowledgeGraph {
    entities: Entity[];
    relations: Relation[];
}
export declare class KnowledgeGraphManager {
    private memoryFilePath;
    constructor(memoryFilePath: string);
    private loadGraph;
    private saveGraph;
    createEntities(entities: Entity[]): Promise<Entity[]>;
    createRelations(relations: Relation[]): Promise<Relation[]>;
    addObservations(observations: {
        entityName: string;
        contents: string[];
    }[]): Promise<{
        entityName: string;
        addedObservations: string[];
    }[]>;
    deleteEntities(entityNames: string[]): Promise<void>;
    deleteObservations(deletions: {
        entityName: string;
        observations: string[];
    }[]): Promise<void>;
    deleteRelations(relations: Relation[]): Promise<void>;
    readGraph(): Promise<KnowledgeGraph>;
    searchNodes(query: string): Promise<KnowledgeGraph>;
    openNodes(names: string[]): Promise<KnowledgeGraph>;
}
