# Phase 5 - Projets et permissions

## Objectif

La plateforme doit fonctionner comme un espace de travail multi-utilisateur:

- chaque utilisateur ne voit que ses projets
- un projet peut être partagé avec d’autres utilisateurs
- les droits sont gérés par projet
- chaque action importante est journalisée
- le chat et les résultats restent liés au projet

## Modèle de droits

Chaque projet possède:

- un propriétaire
- une liste de membres partagés
- des permissions par membre

Permissions supportées:

- `read`
- `write`
- `export`
- `validate`

### Interprétation

- `read`: voir le projet, le chat, l’inventaire et les résultats
- `write`: modifier le projet, rescanner, indexer, lancer des actions de travail
- `export`: générer ou exporter des livrables
- `validate`: marquer un résultat comme vérifié ou approuvé

Le propriétaire et les administrateurs gardent l’accès complet.

## Ce qui est déjà implémenté

Backend:

- filtre automatique des projets visibles par utilisateur
- propriétaire de projet
- partage de projet
- révocation d’accès
- contrôle d’accès par action
- audit lisible des événements de projet
- journal des vues, partages, inventaires, recherches et chats

API:

- `GET /projects`
- `GET /projects/{project_id}`
- `GET /projects/{project_id}/access`
- `POST /projects/{project_id}/share`
- `DELETE /projects/{project_id}/share/{username}`
- `GET /projects/{project_id}/audit`

## Mécanisme d’audit

Chaque action importante écrit une ligne d’audit:

- qui a demandé l’action
- sur quel projet
- quelle action
- avec quelles données

Exemples:

- `project.view`
- `project.access.view`
- `project.inventory.view`
- `project.share`
- `project.share.revoke`
- `project.chat`
- `project.retrieval.search`
- `project.retrieval.index`
- `project.backup`

Les événements sont stockés dans `workspace/audit/audit.jsonl`.

## Résultat attendu

Avec cette phase, le produit doit permettre:

- de partager un projet avec un collègue
- de limiter la visibilité aux projets autorisés
- d’expliquer qui a fait quoi et quand
- d’auditer les réponses générées par l’IA

## Point restant

La couche backend est prête. Si l’on veut une expérience complète dans le client desktop, il faudra ensuite brancher l’UI du desktop sur ces règles de partage, au lieu de rester seulement en local.
